"""Deterministic task artifacts and worker for session synthesis."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, Field

from mente.feature_flags import (
    is_session_synthesis_enabled,
    review_capability_gate,
    session_synthesis_sources,
    session_synthesis_turn_interval,
)
from mente.memory.models import MemoryRecord
from mente.memory.repository import MemoryRepository
from mente.task_core.models import ExecutionResult, Task
from mente.task_core.repository import TaskRepository

logger = logging.getLogger(__name__)

_ARTIFACT_VERSION = "v1"
_FINAL_STATUSES = {"skipped", "not_due", "noop", "persisted"}
_MAX_SUMMARY_CHARS = 240
_MAX_LIST_ITEMS = 5
_MAX_ITEM_CHARS = 160
_MAX_SECTION_ITEMS = 3


class SessionSynthesisOutcome(BaseModel):
    """Compact outcome for one post-turn session synthesis run."""

    status: str
    reason: str | None = None
    turn_count: int = 0
    turn_interval: int = 0
    window_task_ids: list[str] = Field(default_factory=list)
    memory_id: str | None = None


def build_session_synthesis_artifact(task: Task, result: ExecutionResult) -> dict[str, Any]:
    """Persist deterministic, bounded inputs for later session synthesis."""

    return {
        "artifact_version": _ARTIFACT_VERSION,
        "status": _normalize_text(result.status, max_chars=64),
        "assistant_summary": _normalize_text(result.summary, max_chars=_MAX_SUMMARY_CHARS),
        "actions_taken": _normalize_list(result.actions_taken),
        "follow_up_tasks": _normalize_list(result.follow_up_tasks),
        "memory_candidates": _normalize_list(result.memory_candidates),
        "promoted_memory_ids": _promoted_memory_ids(result),
        "requested_execution_mode": task.execution_mode.value,
        "continuity_status": _continuity_status(task, result),
    }


class SessionSynthesisWorker:
    """Review persisted task artifacts and write a stable session summary memory."""

    def __init__(
        self,
        *,
        task_repository: TaskRepository,
        memory_repository: MemoryRepository,
    ) -> None:
        self.task_repository = task_repository
        self.memory_repository = memory_repository

    def review_task(self, task_id: str) -> SessionSynthesisOutcome:
        """Synthesize one session summary when the current turn reaches cadence."""

        task = self.task_repository.get(task_id)
        if task is None:
            return SessionSynthesisOutcome(status="skipped", reason="missing_artifact")

        existing = task.metadata.get("session_synthesis")
        if isinstance(existing, dict) and existing.get("status") in _FINAL_STATUSES:
            return SessionSynthesisOutcome.model_validate(existing)

        enabled, reason = self._review_enabled(task)
        if not enabled:
            return self._persist_outcome(
                task,
                SessionSynthesisOutcome(status="skipped", reason=reason or "disabled"),
            )

        artifact = task.metadata.get("session_synthesis_artifact")
        if not isinstance(artifact, dict):
            return self._persist_outcome(
                task,
                SessionSynthesisOutcome(
                    status="skipped",
                    reason="missing_artifact",
                    turn_interval=self._resolve_turn_interval(task),
                    memory_id=self._build_memory_id(task),
                ),
            )

        eligible_tasks = self._list_eligible_session_tasks(task)
        current_index = next(
            (index for index, item in enumerate(eligible_tasks) if item.task_id == task.task_id),
            None,
        )
        if current_index is None:
            return self._persist_outcome(
                task,
                SessionSynthesisOutcome(
                    status="skipped",
                    reason="missing_artifact",
                    turn_interval=self._resolve_turn_interval(task),
                    memory_id=self._build_memory_id(task),
                ),
            )

        turn_interval = self._resolve_turn_interval(task)
        turn_count = current_index + 1
        memory_id = self._build_memory_id(task)

        if turn_count < turn_interval:
            return self._persist_outcome(
                task,
                SessionSynthesisOutcome(
                    status="not_due",
                    reason="insufficient_turns",
                    turn_count=turn_count,
                    turn_interval=turn_interval,
                    memory_id=memory_id,
                ),
            )

        if turn_count % turn_interval != 0:
            return self._persist_outcome(
                task,
                SessionSynthesisOutcome(
                    status="not_due",
                    reason="cadence_boundary",
                    turn_count=turn_count,
                    turn_interval=turn_interval,
                    memory_id=memory_id,
                ),
            )

        window = eligible_tasks[turn_count - turn_interval:turn_count]
        window_task_ids = [item.task_id for item in window]
        summary = self._render_summary(window)
        if not summary:
            return self._persist_outcome(
                task,
                SessionSynthesisOutcome(
                    status="noop",
                    reason="no_signal",
                    turn_count=turn_count,
                    turn_interval=turn_interval,
                    window_task_ids=window_task_ids,
                    memory_id=memory_id,
                ),
            )

        self.memory_repository.save_resolved_fact(
            self._build_record(
                task,
                fact=summary,
                memory_id=memory_id,
                turn_count=turn_count,
                turn_interval=turn_interval,
                window_task_ids=window_task_ids,
            )
        )
        return self._persist_outcome(
            task,
            SessionSynthesisOutcome(
                status="persisted",
                turn_count=turn_count,
                turn_interval=turn_interval,
                window_task_ids=window_task_ids,
                memory_id=memory_id,
            ),
        )

    def _review_enabled(self, task: Task) -> tuple[bool, str | None]:
        if not is_session_synthesis_enabled():
            return False, "disabled"

        source = str(task.metadata.get("source") or "").strip()
        if not source:
            return False, "missing_source"
        if source not in session_synthesis_sources():
            return False, "unsupported_source"
        if source != "api_server":
            return False, "unsupported_source"
        if task.task_type != "conversation":
            return False, "unsupported_task_type"

        workflow_gate, workflow_reason = review_capability_gate(
            source=source,
            task_type=task.task_type,
            metadata=task.metadata,
            capability="session_synthesis",
        )
        if workflow_gate is True:
            return True, None
        return False, workflow_reason or "workflow_contract_disabled"

    def _list_eligible_session_tasks(self, task: Task) -> list[Task]:
        source = str(task.metadata.get("source") or "").strip()
        session_tasks = self._list_session_tasks(
            session_id=task.session_id,
            source=source,
            task_type=task.task_type,
        )
        return [item for item in session_tasks if self._task_is_eligible(item)]

    def _list_session_tasks(
        self,
        *,
        session_id: str,
        source: str,
        task_type: str,
    ) -> list[Task]:
        batch_size = 200
        offset = 0
        collected: list[Task] = []
        while True:
            page = self.task_repository.list_by_session(
                session_id,
                limit=batch_size,
                offset=offset,
                source=source,
                task_type=task_type,
            )
            if not page:
                break
            collected.extend(page)
            if len(page) < batch_size:
                break
            offset += batch_size
        collected.reverse()
        return collected

    def _task_is_eligible(self, task: Task) -> bool:
        artifact = task.metadata.get("session_synthesis_artifact")
        if not isinstance(artifact, Mapping):
            return False
        source = str(task.metadata.get("source") or "").strip()
        if source != "api_server" or task.task_type != "conversation":
            return False
        workflow_gate, _ = review_capability_gate(
            source=source,
            task_type=task.task_type,
            metadata=task.metadata,
            capability="session_synthesis",
        )
        return workflow_gate is True

    def _resolve_turn_interval(self, task: Task) -> int:
        contract = task.metadata.get("workflow_contract")
        if isinstance(contract, Mapping):
            capability = contract.get("session_synthesis")
            if isinstance(capability, Mapping):
                raw_interval = capability.get("turn_interval")
                try:
                    interval = int(raw_interval)
                except (TypeError, ValueError):
                    interval = 0
                if interval > 0:
                    return interval
        return session_synthesis_turn_interval()

    def _build_memory_id(self, task: Task) -> str:
        workflow_id = self._workflow_id(task)
        source = str(task.metadata.get("source") or "").strip() or "unknown"
        return f"session_summary:{source}:{task.session_id}:{workflow_id}"

    def _workflow_id(self, task: Task) -> str:
        contract = task.metadata.get("workflow_contract")
        if isinstance(contract, Mapping):
            workflow_id = str(contract.get("workflow_id") or "").strip()
            if workflow_id:
                return workflow_id
        return "unknown_workflow"

    def _render_summary(self, window: list[Task]) -> str:
        preferences = self._collect_window_items(window, key="memory_candidates")
        completed_work = self._collect_window_items(window, key="assistant_summary")
        follow_ups = self._collect_window_items(window, key="follow_up_tasks")
        continuity = self._collect_continuity(window)

        lines = ["Session summary:"]
        if preferences:
            lines.append(f"- Stable preferences: {'; '.join(preferences)}")
        if completed_work:
            lines.append(f"- Recent completed work: {'; '.join(completed_work)}")
        if follow_ups:
            lines.append(f"- Open follow-ups: {'; '.join(follow_ups)}")
        if continuity:
            lines.append(f"- Continuity: {'; '.join(continuity)}")

        if len(lines) == 1:
            return ""
        return "\n".join(lines)

    def _collect_window_items(self, window: list[Task], *, key: str) -> list[str]:
        items: list[str] = []
        seen: set[str] = set()
        for task in reversed(window):
            artifact = task.metadata.get("session_synthesis_artifact")
            if not isinstance(artifact, Mapping):
                continue
            raw_value = artifact.get(key)
            values = raw_value if isinstance(raw_value, list) else [raw_value]
            for raw_item in values:
                text = _normalize_text(raw_item, max_chars=_MAX_ITEM_CHARS)
                if not text or text in seen:
                    continue
                seen.add(text)
                items.append(text)
                if len(items) >= _MAX_SECTION_ITEMS:
                    return items
        return items

    def _collect_continuity(self, window: list[Task]) -> list[str]:
        items: list[str] = []
        seen: set[str] = set()
        for task in reversed(window):
            artifact = task.metadata.get("session_synthesis_artifact")
            if not isinstance(artifact, Mapping):
                continue
            status = _normalize_text(artifact.get("continuity_status"), max_chars=64)
            if not status or status in {"stateless", "unknown"} or status in seen:
                continue
            seen.add(status)
            items.append(status)
            if len(items) >= _MAX_SECTION_ITEMS:
                return items
        return items

    def _build_record(
        self,
        task: Task,
        *,
        fact: str,
        memory_id: str,
        turn_count: int,
        turn_interval: int,
        window_task_ids: list[str],
    ) -> MemoryRecord:
        source = str(task.metadata.get("source") or "").strip()
        return MemoryRecord(
            memory_id=memory_id,
            session_id=task.session_id,
            task_id=task.task_id,
            task_type=task.task_type,
            source=source,
            scope="session",
            kind="session_summary",
            score=2.0,
            fact=fact,
            metadata={
                "write_origin": "session_synthesis",
                "promotion_reason": "session_synthesis",
                "source_task_id": task.task_id,
                "window_task_ids": list(window_task_ids),
                "turn_count": turn_count,
                "turn_interval": turn_interval,
                "artifact_version": _ARTIFACT_VERSION,
                "workflow_id": self._workflow_id(task),
            },
        )

    def _persist_outcome(self, task: Task, outcome: SessionSynthesisOutcome) -> SessionSynthesisOutcome:
        try:
            task.metadata["session_synthesis"] = outcome.model_dump(mode="json")
            self.task_repository.save(task)
        except Exception:
            logger.exception("failed to persist session synthesis outcome for task %s", task.task_id)
        return outcome


def _normalize_list(items: list[Any]) -> list[str]:
    normalized: list[str] = []
    for item in items[:_MAX_LIST_ITEMS]:
        text = _normalize_text(item, max_chars=_MAX_ITEM_CHARS)
        if text:
            normalized.append(text)
    return normalized


def _normalize_text(value: Any, *, max_chars: int) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip()


def _promoted_memory_ids(result: ExecutionResult) -> list[str]:
    payload = result.metadata.get("memory_promotion")
    if not isinstance(payload, dict):
        return []
    memory_ids = payload.get("promoted_memory_ids")
    if not isinstance(memory_ids, list):
        return []
    normalized: list[str] = []
    for item in memory_ids[:_MAX_LIST_ITEMS]:
        text = _normalize_text(item, max_chars=_MAX_ITEM_CHARS)
        if text:
            normalized.append(text)
    return normalized


def _continuity_status(task: Task, result: ExecutionResult) -> str:
    payload = result.metadata.get("execution_session")
    if isinstance(payload, dict):
        text = _normalize_text(payload.get("continuity_status"), max_chars=64)
        if text:
            return text
    if task.execution_mode.value == "stateless":
        return "stateless"
    return "unknown"
