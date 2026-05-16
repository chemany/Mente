"""Deterministic worker-lane summary cache helpers."""

from __future__ import annotations

from typing import Any

from mente.memory.context import build_worker_lane_summary_kind
from mente.memory.models import MemoryRecord
from mente.memory.repository import MemoryRepository
from mente.task_core.models import ExecutionResult, Task, TaskRole

_ARTIFACT_VERSION = "v1"
_MAX_SUMMARY_CHARS = 240
_MAX_LIST_ITEMS = 5
_MAX_ITEM_CHARS = 160
_MAX_SECTION_ITEMS = 3


def build_worker_summary_memory_id(task: Task) -> str:
    """Return the stable session-scoped cache id for one worker lane."""

    source = str(task.metadata.get("source") or "").strip() or "unknown"
    lane = _normalize_lane(task.worker_lane)
    return f"worker_lane_summary:{source}:{task.session_id}:{lane}"


def build_worker_summary_artifact(task: Task, result: ExecutionResult) -> dict[str, Any]:
    """Build a bounded, deterministic artifact for one worker result."""

    return {
        "artifact_version": _ARTIFACT_VERSION,
        "lane": _normalize_lane(task.worker_lane),
        "status": _normalize_text(result.status, max_chars=64),
        "assistant_summary": _normalize_text(result.summary, max_chars=_MAX_SUMMARY_CHARS),
        "actions_taken": _normalize_list(result.actions_taken),
        "follow_up_tasks": _normalize_list(result.follow_up_tasks),
        "changed_files": _normalize_list(result.changed_files),
        "artifacts_out": _normalize_list(result.artifacts_out),
    }


def persist_worker_summary_cache(
    *,
    task: Task,
    result: ExecutionResult,
    memory_repository: MemoryRepository,
) -> dict[str, Any] | None:
    """Persist the latest worker-lane summary cache when applicable."""

    if task.task_type != "conversation":
        return None
    if task.role is not TaskRole.WORKER:
        return None
    lane = _normalize_lane(task.worker_lane)
    if not lane:
        return {
            "status": "skipped",
            "reason": "missing_worker_lane",
        }
    if result.status != "success":
        return {
            "status": "skipped",
            "reason": "result_not_success",
            "lane": lane,
        }

    artifact = build_worker_summary_artifact(task, result)
    fact = _render_worker_summary_fact(artifact)
    if not fact:
        return {
            "status": "noop",
            "reason": "no_signal",
            "lane": lane,
        }

    memory_id = build_worker_summary_memory_id(task)
    kind = build_worker_lane_summary_kind(lane)
    source = str(task.metadata.get("source") or "").strip() or "unknown"
    memory_repository.save_resolved_fact(
        MemoryRecord(
            memory_id=memory_id,
            session_id=task.session_id,
            task_id=task.task_id,
            task_type=task.task_type,
            source=source,
            scope="session",
            kind=kind,
            score=3.0,
            fact=fact,
            metadata={
                "write_origin": "worker_summary_cache",
                "promotion_reason": "worker_summary_cache",
                "artifact_version": _ARTIFACT_VERSION,
                "lane": lane,
                "source_task_id": task.task_id,
            },
        )
    )
    return {
        "status": "persisted",
        "memory_id": memory_id,
        "kind": kind,
        "lane": lane,
    }


def _render_worker_summary_fact(artifact: dict[str, Any]) -> str:
    lane = _normalize_text(artifact.get("lane"), max_chars=64)
    assistant_summary = _normalize_text(artifact.get("assistant_summary"), max_chars=_MAX_SUMMARY_CHARS)
    actions_taken = _normalize_list(artifact.get("actions_taken") or [])
    follow_up_tasks = _normalize_list(artifact.get("follow_up_tasks") or [])
    changed_files = _normalize_list(artifact.get("changed_files") or [])
    artifacts_out = _normalize_list(artifact.get("artifacts_out") or [])

    if not lane or not assistant_summary:
        return ""

    lines = [f"Worker lane summary ({lane}): {assistant_summary}"]
    if actions_taken:
        lines.append(f"- Actions taken: {'; '.join(actions_taken[:_MAX_SECTION_ITEMS])}")
    if follow_up_tasks:
        lines.append(f"- Follow-ups: {'; '.join(follow_up_tasks[:_MAX_SECTION_ITEMS])}")
    if changed_files:
        lines.append(f"- Changed files: {'; '.join(changed_files[:_MAX_SECTION_ITEMS])}")
    if artifacts_out:
        lines.append(f"- Artifacts: {'; '.join(artifacts_out[:_MAX_SECTION_ITEMS])}")
    return "\n".join(lines)


def _normalize_lane(value: object) -> str:
    return str(value or "").strip().lower()


def _normalize_list(items: list[Any]) -> list[str]:
    normalized: list[str] = []
    for item in list(items)[:_MAX_LIST_ITEMS]:
        text = _normalize_text(item, max_chars=_MAX_ITEM_CHARS)
        if text:
            normalized.append(text)
    return normalized


def _normalize_text(value: Any, *, max_chars: int) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip()
