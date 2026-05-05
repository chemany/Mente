"""Mente-owned post-turn memory review worker."""

from __future__ import annotations

import logging
import re
from typing import Any

from pydantic import BaseModel, Field

from mente.feature_flags import (
    is_memory_review_enabled,
    parse_allowed_sources,
    review_capability_gate,
)
from mente.memory.context import persist_memory_fact
from mente.memory.fact_normalization import normalize_memory_fact_text
from mente.memory.models import MemoryRecord
from mente.memory.repository import MemoryRepository
from mente.review.remember_intent import extract_explicit_remember_intent_fact
from mente.task_core.models import ExecutionResult, Task
from mente.task_core.repository import TaskRepository

logger = logging.getLogger(__name__)

_PREFERENCE_RE = re.compile(r"\bi prefer\s+(.+?)\s*$", re.IGNORECASE)
_NAME_RE = re.compile(r"\bmy name is\s+(.+?)\s*$", re.IGNORECASE)
_CHINESE_PREFERENCE_RE = re.compile(r"^\s*(我(?:更)?喜欢.+?|我偏好.+?)\s*$")


class MemoryReviewOutcome(BaseModel):
    """Compact outcome for one post-turn memory review run."""

    status: str
    reason: str | None = None
    candidate_count: int = 0
    persisted_count: int = 0
    memory_ids: list[str] = Field(default_factory=list)


def build_memory_review_artifact(task: Task, result: ExecutionResult) -> dict[str, Any]:
    """Persist the minimal task/result fields needed for post-turn review."""

    return {
        "assistant_summary": result.summary,
        "status": result.status,
    }


class MemoryReviewWorker:
    """Review persisted task artifacts and write durable memories back to Mente."""

    def __init__(
        self,
        *,
        task_repository: TaskRepository,
        memory_repository: MemoryRepository,
    ) -> None:
        self.task_repository = task_repository
        self.memory_repository = memory_repository

    def review_task(self, task_id: str) -> MemoryReviewOutcome:
        """Review one persisted task and persist any durable memory updates."""

        task = self.task_repository.get(task_id)
        if task is None:
            return MemoryReviewOutcome(status="skipped", reason="missing_artifact")

        existing = task.metadata.get("memory_review")
        if isinstance(existing, dict) and existing.get("status") in {"skipped", "noop", "persisted"}:
            return MemoryReviewOutcome.model_validate(existing)

        enabled, reason = self._review_enabled(task)
        if not enabled:
            return self._persist_outcome(
                task,
                MemoryReviewOutcome(status="skipped", reason=reason or "disabled"),
            )

        artifact = task.metadata.get("memory_review_artifact")
        if not isinstance(artifact, dict):
            return self._persist_outcome(
                task,
                MemoryReviewOutcome(status="skipped", reason="missing_artifact"),
            )

        candidates = self._extract_candidates(task, artifact)
        if not candidates:
            return self._persist_outcome(task, MemoryReviewOutcome(status="noop"))

        persisted: list[MemoryRecord] = []
        duplicate_existing = False
        superseded_existing = False
        source = str(task.metadata.get("source") or "").strip()
        scope = self._target_scope(task)
        for fact in candidates:
            record, write_reason = persist_memory_fact(
                task,
                fact=fact,
                memory_repository=self.memory_repository,
                scope=scope,
                source=source,
                tool_name="mente_memory_review_worker",
                write_origin="post_turn_memory_review",
                memory_id=f"{task.task_id}:review:{len(persisted)}",
            )
            if write_reason == "duplicate_existing":
                duplicate_existing = True
                continue
            if record is None:
                continue
            if write_reason == "superseded_existing":
                superseded_existing = True
            persisted.append(record)

        if not persisted:
            return self._persist_outcome(
                task,
                MemoryReviewOutcome(
                    status="noop",
                    reason="duplicate_existing" if duplicate_existing else None,
                    candidate_count=len(candidates),
                    persisted_count=0,
                ),
            )

        return self._persist_outcome(
            task,
            MemoryReviewOutcome(
                status="persisted",
                reason="superseded_existing" if superseded_existing else None,
                candidate_count=len(candidates),
                persisted_count=len(persisted),
                memory_ids=[record.memory_id for record in persisted],
            ),
        )

    def _review_enabled(self, task: Task) -> tuple[bool, str | None]:
        if not is_memory_review_enabled():
            return False, "disabled"

        source = str(task.metadata.get("source") or "").strip()
        if not source:
            return False, "missing_source"

        workflow_gate, workflow_reason = review_capability_gate(
            source=source,
            task_type=task.task_type,
            metadata=task.metadata,
            capability="memory_review",
        )
        if workflow_gate is not None:
            return workflow_gate, workflow_reason

        allowed_sources = parse_allowed_sources(
            "MENTE_MEMORY_REVIEW_SOURCES",
            default_sources=("gateway",),
        )
        if source not in allowed_sources:
            return False, "unsupported_source"

        if task.task_type != "conversation":
            return False, "unsupported_task_type"
        return True, None

    def _extract_candidates(self, task: Task, artifact: dict[str, Any]) -> list[str]:
        candidates: list[str] = []
        seen: set[str] = set()
        for text in (
            task.user_request,
            str(artifact.get("assistant_summary") or ""),
        ):
            for fact in self._extract_candidates_from_text(text):
                if fact in seen:
                    continue
                seen.add(fact)
                candidates.append(fact)
        return candidates

    def _extract_candidates_from_text(self, text: str) -> list[str]:
        candidates: list[str] = []
        for raw_line in text.splitlines():
            line = " ".join(raw_line.strip().split())
            if not line:
                continue

            explicit_fact = extract_explicit_remember_intent_fact(line)
            if explicit_fact is not None:
                fact = normalize_memory_fact_text(explicit_fact)
                if fact:
                    candidates.append(fact)
                continue

            preference_match = _PREFERENCE_RE.search(line)
            if preference_match is not None:
                fact = normalize_memory_fact_text(f"I prefer {preference_match.group(1)}")
                if fact:
                    candidates.append(fact)
                continue

            chinese_preference_match = _CHINESE_PREFERENCE_RE.match(line)
            if chinese_preference_match is not None:
                fact = normalize_memory_fact_text(chinese_preference_match.group(1))
                if fact:
                    candidates.append(fact)
                continue

            name_match = _NAME_RE.search(line)
            if name_match is not None:
                fact = normalize_memory_fact_text(f"My name is {name_match.group(1)}")
                if fact:
                    candidates.append(fact)
        return candidates

    def _target_scope(self, task: Task) -> str:
        source = str(task.metadata.get("source") or "").strip()
        if task.task_type == "conversation" and source in {"gateway", "api_server"}:
            return "session"
        return "task_type"

    def _persist_outcome(self, task: Task, outcome: MemoryReviewOutcome) -> MemoryReviewOutcome:
        try:
            task.metadata["memory_review"] = outcome.model_dump(mode="json")
            self.task_repository.save(task)
        except Exception:
            logger.exception("failed to persist memory review outcome for task %s", task.task_id)
        return outcome
