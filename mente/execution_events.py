"""Small shared execution-event helpers for Mente runtime progress."""

from __future__ import annotations

from datetime import datetime, timezone
import logging
from pathlib import Path
import shlex
from typing import Any, Callable

from mente.task_core.models import ExecutionResult


ExecutionEventCallback = Callable[[str, dict[str, Any]], None]

_LANE_DISPLAY_LABELS = {
    "director": "Mente ",
    "engineering": "工程部",
    "research": "市场部",
    "writing": "编辑部",
    "config_admin": "内务府",
}
_SUMMARY_ITEM_LIMIT = 5
_SUMMARY_TEXT_LIMIT = 240


def emit_execution_event(
    callback: ExecutionEventCallback | None,
    event_type: str,
    payload: dict[str, Any],
    *,
    logger: logging.Logger,
) -> None:
    """Best-effort event emission for realtime execution progress."""
    if callback is None:
        return

    try:
        callback(event_type, payload)
    except Exception:
        logger.exception("failed to emit execution event %s", event_type)


def normalize_lane_progress_event(
    event_type: str,
    payload: dict[str, Any] | None,
    *,
    lane: str,
    task_id: str | None,
) -> tuple[str, dict[str, Any]] | None:
    """Normalize low-level runtime events into one structured lane event."""
    normalized_type = str(event_type or "").strip()
    normalized_payload = payload if isinstance(payload, dict) else {}
    lane_name = str(lane or "").strip().lower() or "director"
    effective_task_id = str(task_id or normalized_payload.get("task_id") or "").strip() or None

    if normalized_type == "kernel.codex.command.started":
        detail = _summarize_command(str(normalized_payload.get("command") or ""))
        if not detail:
            return None
        return "lane.progress", _build_lane_payload(
            lane=lane_name,
            task_id=effective_task_id,
            status="running",
            headline="正在执行",
            detail=detail,
            source_event=normalized_type,
        )
    if normalized_type == "kernel.codex.command.completed":
        detail = _summarize_command(str(normalized_payload.get("command") or ""))
        if not detail:
            return None
        exit_code = normalized_payload.get("exit_code")
        if exit_code not in (None, 0):
            return "lane.blocked", _build_lane_payload(
                lane=lane_name,
                task_id=effective_task_id,
                status="blocked",
                headline="执行失败",
                detail=detail,
                blocked_reason=f"exit_code:{exit_code}",
                source_event=normalized_type,
            )
        return "lane.progress", _build_lane_payload(
            lane=lane_name,
            task_id=effective_task_id,
            status="running",
            headline="已完成执行",
            detail=detail,
            source_event=normalized_type,
        )
    if normalized_type == "kernel.codex.mcp_tool.started":
        detail = _summarize_tool_name(str(normalized_payload.get("tool") or ""))
        if not detail:
            return None
        return "lane.progress", _build_lane_payload(
            lane=lane_name,
            task_id=effective_task_id,
            status="running",
            headline="正在调用工具",
            detail=detail,
            source_event=normalized_type,
        )
    if normalized_type == "kernel.codex.mcp_tool.completed":
        detail = _summarize_tool_name(str(normalized_payload.get("tool") or ""))
        if not detail:
            return None
        if normalized_payload.get("error"):
            return "lane.blocked", _build_lane_payload(
                lane=lane_name,
                task_id=effective_task_id,
                status="blocked",
                headline="工具执行失败",
                detail=detail,
                blocked_reason=str(normalized_payload.get("error") or "").strip() or None,
                source_event=normalized_type,
            )
        return "lane.progress", _build_lane_payload(
            lane=lane_name,
            task_id=effective_task_id,
            status="running",
            headline="已完成工具调用",
            detail=detail,
            source_event=normalized_type,
        )
    if normalized_type == "kernel.codex.web_search.started":
        detail = _truncate_text(str(normalized_payload.get("query") or ""), limit=48)
        if not detail:
            return None
        return "lane.progress", _build_lane_payload(
            lane=lane_name,
            task_id=effective_task_id,
            status="running",
            headline="正在检索信息",
            detail=detail,
            source_event=normalized_type,
        )
    return None


def build_lane_terminal_event(
    result: ExecutionResult,
    *,
    lane: str,
    task_id: str | None,
) -> tuple[str, dict[str, Any]]:
    """Build one terminal lane event from a completed execution result."""
    lane_name = str(lane or "").strip().lower() or "director"
    effective_task_id = str(task_id or result.metadata.get("task_id") or "").strip() or None
    normalized_status = str(result.status or "").strip().lower()
    failure_reason = str(result.failure_reason or "").strip() or None
    if normalized_status == "success":
        return "lane.completed", _build_lane_payload(
            lane=lane_name,
            task_id=effective_task_id,
            status="completed",
            headline="任务已完成",
            detail=_truncate_text(result.summary, limit=180),
            changed_files=list(result.changed_files),
            artifacts=list(result.artifacts_out),
            source_event="execution.result",
            checkpoint=True,
        )
    summary = _truncate_text(result.summary or failure_reason, limit=180)
    if failure_reason == "interrupted_by_user":
        return "lane.cancelled", _build_lane_payload(
            lane=lane_name,
            task_id=effective_task_id,
            status="cancelled",
            headline="任务已取消",
            detail=summary,
            changed_files=list(result.changed_files),
            artifacts=list(result.artifacts_out),
            source_event="execution.result",
            failure_reason=failure_reason,
            checkpoint=True,
        )
    if normalized_status == "blocked":
        return "lane.blocked", _build_lane_payload(
            lane=lane_name,
            task_id=effective_task_id,
            status="blocked",
            headline="任务已阻塞",
            detail=summary,
            changed_files=list(result.changed_files),
            artifacts=list(result.artifacts_out),
            source_event="execution.result",
            blocked_reason=failure_reason or summary,
            checkpoint=True,
        )
    return "lane.failed", _build_lane_payload(
        lane=lane_name,
        task_id=effective_task_id,
        status="failed",
        headline="任务执行失败",
        detail=summary,
        changed_files=list(result.changed_files),
        artifacts=list(result.artifacts_out),
        source_event="execution.result",
        failure_reason=failure_reason or summary,
        checkpoint=True,
    )


def render_lane_progress_text(
    event_type: str,
    payload: dict[str, Any] | None,
) -> str | None:
    """Render one structured lane event into one lane-branded progress line."""
    normalized_payload = payload if isinstance(payload, dict) else {}
    lane_name = str(normalized_payload.get("lane") or "").strip().lower() or "director"
    lane_label = _LANE_DISPLAY_LABELS.get(lane_name, "Mente ")
    headline = str(normalized_payload.get("headline") or "").strip()
    detail = str(normalized_payload.get("detail") or "").strip()
    if not headline:
        return None
    if detail:
        return f"{lane_label}{headline}：{detail}"
    return f"{lane_label}{headline}"


def _build_lane_payload(
    *,
    lane: str,
    task_id: str | None,
    status: str,
    headline: str,
    detail: str | None = None,
    changed_files: list[str] | None = None,
    artifacts: list[str] | None = None,
    source_event: str | None = None,
    blocked_reason: str | None = None,
    failure_reason: str | None = None,
    checkpoint: bool = False,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "lane": lane,
        "task_id": task_id,
        "status": status,
        "headline": headline,
        "detail": detail or "",
        "changed_files": list(changed_files or []),
        "artifacts": list(artifacts or []),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if source_event:
        payload["source_event"] = source_event
    if blocked_reason:
        payload["blocked_reason"] = blocked_reason
    if failure_reason:
        payload["failure_reason"] = failure_reason
    if checkpoint:
        payload["checkpoint"] = True
    return payload


def persist_lane_progress_event(
    repository: Any,
    *,
    event_type: str,
    payload: dict[str, Any] | None,
    session_id: str,
    lane: str,
    task_id: str | None,
    job_id: str | None = None,
    skill_refs: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Normalize one runtime event, append it to mente_task_events, and roll job summary."""
    lane_event = normalize_lane_progress_event(
        event_type,
        payload,
        lane=lane,
        task_id=task_id,
    )
    if lane_event is None:
        return None
    lane_event_type, lane_payload = lane_event
    return persist_lane_event(
        repository,
        session_id=session_id,
        lane=lane,
        task_id=task_id,
        job_id=job_id,
        event_type=lane_event_type,
        payload=lane_payload,
        skill_refs=skill_refs,
        metadata=metadata,
    )


def persist_lane_terminal_event(
    repository: Any,
    *,
    result: ExecutionResult,
    session_id: str,
    lane: str,
    task_id: str | None,
    job_id: str | None = None,
    skill_refs: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Append one final lane checkpoint and update the job summary snapshot."""
    lane_event_type, lane_payload = build_lane_terminal_event(
        result,
        lane=lane,
        task_id=task_id,
    )
    return persist_lane_event(
        repository,
        session_id=session_id,
        lane=lane,
        task_id=task_id,
        job_id=job_id,
        event_type=lane_event_type,
        payload=lane_payload,
        skill_refs=skill_refs,
        metadata=metadata,
    )


def persist_lane_event(
    repository: Any,
    *,
    session_id: str,
    lane: str,
    task_id: str | None,
    job_id: str | None,
    event_type: str,
    payload: dict[str, Any] | None,
    skill_refs: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Persist one normalized lane event and update the session job summary row."""
    if repository is None or not hasattr(repository, "append_task_event"):
        raise ValueError("repository with append_task_event() is required")
    normalized_payload = payload if isinstance(payload, dict) else {}
    effective_task_id = str(
        task_id or normalized_payload.get("task_id") or ""
    ).strip()
    if not effective_task_id:
        raise ValueError("task_id is required to persist lane events")
    normalized_lane = str(
        normalized_payload.get("lane") or lane or ""
    ).strip().lower() or "director"
    stored_event = repository.append_task_event(
        task_id=effective_task_id,
        session_id=str(session_id),
        lane=normalized_lane,
        event_type=str(event_type or "").strip(),
        payload=normalized_payload,
    )
    _update_session_job_from_lane_event(
        repository,
        session_id=str(session_id),
        lane=normalized_lane,
        task_id=effective_task_id,
        job_id=str(job_id or "").strip() or None,
        event_type=str(event_type or "").strip(),
        payload=normalized_payload,
        skill_refs=skill_refs,
        metadata=metadata,
    )
    return stored_event


def persist_session_job_state(
    repository: Any,
    *,
    session_id: str,
    lane: str,
    task_id: str,
    job_id: str,
    status: str,
    summary: str | None = None,
    skill_refs: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Mirror one live worker state transition into mente_session_jobs."""
    if repository is None or not hasattr(repository, "bind_session_job"):
        return None
    existing = None
    if hasattr(repository, "get_session_job"):
        existing = repository.get_session_job(session_id, lane)
    existing_metadata = _job_metadata(existing)
    merged_metadata = {
        **existing_metadata,
        **_normalize_metadata(metadata),
    }
    effective_summary = str(summary or "").strip() or str(existing_metadata.get("summary") or "").strip()
    repository.bind_session_job(
        session_id,
        lane=lane,
        job_id=job_id,
        task_id=task_id,
        status=str(status or "").strip().lower() or "running",
        summary=effective_summary,
        skill_refs=_normalize_string_list(
            skill_refs
            if skill_refs is not None
            else existing.get("skill_refs") if isinstance(existing, dict) else []
        ),
        metadata=merged_metadata,
    )
    if hasattr(repository, "get_session_job"):
        return repository.get_session_job(session_id, lane)
    return None


def read_persisted_lane_job(
    repository: Any,
    *,
    session_id: str,
    lane: str,
    job_id: str | None = None,
    task_id: str | None = None,
) -> dict[str, Any] | None:
    """Load one coordinator-readable persisted worker snapshot."""
    if repository is None or not hasattr(repository, "get_session_job"):
        return None
    job = repository.get_session_job(session_id, lane)
    if not isinstance(job, dict):
        return None
    if job_id is not None and str(job.get("job_id") or "").strip() != str(job_id).strip():
        return None
    if task_id is not None and str(job.get("task_id") or "").strip() != str(task_id).strip():
        return None
    metadata = _job_metadata(job)
    summary_items = _normalize_string_list(metadata.get("summary_items"))
    if not summary_items and hasattr(repository, "list_task_events"):
        summary_items = _summary_items_from_events(
            repository.list_task_events(str(job.get("task_id") or ""), limit=_SUMMARY_ITEM_LIMIT)
        )
    return {
        **job,
        "metadata": metadata,
        "latest_job_state": str(metadata.get("job_state") or job.get("status") or "").strip(),
        "summary_items": summary_items,
        "blocked_reason": str(metadata.get("blocked_reason") or "").strip() or None,
        "failure_reason": str(metadata.get("failure_reason") or "").strip() or None,
        "latest_event_type": str(metadata.get("latest_event_type") or "").strip() or None,
    }


def merge_live_and_persisted_lane_job(
    live_job: dict[str, Any] | None,
    persisted_job: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Overlay persisted progress details onto one live job payload."""
    if live_job is None:
        return dict(persisted_job) if isinstance(persisted_job, dict) else None
    merged = dict(live_job)
    if not isinstance(persisted_job, dict):
        return merged
    merged["summary"] = str(persisted_job.get("summary") or merged.get("summary") or "").strip()
    merged["status"] = str(persisted_job.get("latest_job_state") or persisted_job.get("status") or merged.get("status") or "").strip() or merged.get("status")
    merged["metadata"] = {
        **dict(merged.get("metadata") or {}),
        **dict(persisted_job.get("metadata") or {}),
    }
    merged["summary_items"] = list(persisted_job.get("summary_items") or [])
    merged["blocked_reason"] = persisted_job.get("blocked_reason")
    merged["failure_reason"] = persisted_job.get("failure_reason")
    merged["latest_event_type"] = persisted_job.get("latest_event_type")
    return merged


def _update_session_job_from_lane_event(
    repository: Any,
    *,
    session_id: str,
    lane: str,
    task_id: str,
    job_id: str | None,
    event_type: str,
    payload: dict[str, Any],
    skill_refs: list[str] | None,
    metadata: dict[str, Any] | None,
) -> None:
    if not hasattr(repository, "bind_session_job"):
        return
    existing = repository.get_session_job(session_id, lane) if hasattr(repository, "get_session_job") else None
    existing_job_id = str(existing.get("job_id") or "").strip() if isinstance(existing, dict) else ""
    existing_status = str(existing.get("status") or "").strip() if isinstance(existing, dict) else ""
    existing_metadata = _job_metadata(existing)
    summary_items = _normalize_string_list(existing_metadata.get("summary_items"))
    summary_item = render_lane_progress_text(event_type, payload)
    if summary_item:
        summary_items = _roll_summary_items(summary_items, summary_item)
    merged_metadata = {
        **existing_metadata,
        **_normalize_metadata(metadata),
        "job_state": str(payload.get("status") or existing_metadata.get("job_state") or "running").strip().lower() or "running",
        "summary_items": summary_items,
        "summary": "；".join(summary_items),
        "latest_event_type": event_type,
        "latest_event_payload": dict(payload),
        "latest_event_timestamp": payload.get("timestamp"),
    }
    blocked_reason = str(payload.get("blocked_reason") or "").strip()
    if blocked_reason:
        merged_metadata["blocked_reason"] = blocked_reason
    failure_reason = str(payload.get("failure_reason") or "").strip()
    if failure_reason:
        merged_metadata["failure_reason"] = failure_reason
    if payload.get("checkpoint"):
        merged_metadata["final_checkpoint"] = {
            "event_type": event_type,
            "status": str(payload.get("status") or "").strip(),
            "headline": str(payload.get("headline") or "").strip(),
            "detail": str(payload.get("detail") or "").strip(),
            "timestamp": payload.get("timestamp"),
        }
    repository.bind_session_job(
        session_id,
        lane=lane,
        job_id=str(job_id or existing_job_id or task_id),
        task_id=task_id,
        status=str(payload.get("status") or existing_status or "running").strip().lower() or "running",
        summary=_truncate_text("；".join(summary_items), limit=_SUMMARY_TEXT_LIMIT),
        skill_refs=_normalize_string_list(
            skill_refs
            if skill_refs is not None
            else existing.get("skill_refs") if isinstance(existing, dict) else []
        ),
        metadata=merged_metadata,
    )


def _job_metadata(job: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(job, dict):
        return {}
    metadata = job.get("metadata")
    return dict(metadata) if isinstance(metadata, dict) else {}


def _normalize_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
    return dict(metadata) if isinstance(metadata, dict) else {}


def _normalize_string_list(value: Any) -> list[str]:
    items = value if isinstance(value, list) else []
    return [str(item).strip() for item in items if str(item).strip()]


def _roll_summary_items(items: list[str], summary_item: str) -> list[str]:
    rolled = list(items)
    value = str(summary_item or "").strip()
    if not value:
        return rolled
    if value in rolled:
        rolled.remove(value)
    rolled.append(value)
    if len(rolled) > _SUMMARY_ITEM_LIMIT:
        del rolled[:-_SUMMARY_ITEM_LIMIT]
    return rolled


def _summary_items_from_events(events: list[dict[str, Any]]) -> list[str]:
    rolled: list[str] = []
    for event in reversed(events):
        payload = event.get("payload") if isinstance(event, dict) else None
        summary_item = render_lane_progress_text(
            str(event.get("event_type") or "") if isinstance(event, dict) else "",
            payload if isinstance(payload, dict) else {},
        )
        if summary_item:
            rolled = _roll_summary_items(rolled, summary_item)
    return rolled


def _summarize_tool_name(tool_name: str) -> str:
    value = str(tool_name or "").strip()
    if not value:
        return ""
    if value.startswith("mcp__"):
        parts = [part for part in value.split("__") if part]
        if parts:
            return parts[-1]
    return value


def _summarize_command(command: str) -> str:
    text = str(command or "").strip()
    if not text:
        return ""
    try:
        tokens = shlex.split(text, posix=True)
    except ValueError:
        tokens = text.split()
    if not tokens:
        return ""
    shell_name = Path(tokens[0]).name.strip().lower()
    if shell_name in {"bash", "sh", "zsh", "fish"}:
        shell_label = shell_name.capitalize()
        for index, token in enumerate(tokens[1:], start=1):
            if token in {"-c", "-lc"} and index + 1 < len(tokens):
                inner_command = tokens[index + 1]
                inner_summary = _summarize_command(inner_command)
                return f"{shell_label} · {inner_summary}" if inner_summary else f"{shell_label} 命令"
        return f"{shell_label} 命令"
    head = Path(tokens[0]).name.strip().lower()
    args = [str(token or "").strip() for token in tokens[1:]]
    if head == "sed":
        target = _first_path_token(args)
        return f"sed {target}" if target else "sed"
    if head == "rg":
        pattern = next((token for token in args if token and not token.startswith("-")), "")
        path_token = _first_path_token(args)
        parts = ["rg"]
        if pattern:
            parts.append(_truncate_text(pattern, limit=24))
        if path_token:
            parts.append(path_token)
        return " ".join(parts).strip()
    if head in {"python", "python3", "py"}:
        if " -c " in text or "\n" in text or "<<'" in text or '<<"' in text:
            return "Python 脚本（内联）"
        target = _first_path_token(args)
        return f"Python 脚本 {target}" if target else "Python 脚本"
    if head == "node":
        target = _first_path_token(args)
        return f"Node 脚本 {target}" if target else "Node 脚本"
    target = _first_path_token(args)
    return f"{head} {target}".strip() if target else head


def _first_path_token(tokens: list[str]) -> str | None:
    for token in tokens:
        value = str(token or "").strip().strip("\"'")
        if not value or value.startswith("-"):
            continue
        if "://" in value:
            continue
        if "/" in value or "." in value or value.startswith("~"):
            return Path(value).name or value
    return None


def _truncate_text(value: str | None, *, limit: int) -> str:
    text = " ".join(str(value or "").split()).strip().strip("\"'")
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."
