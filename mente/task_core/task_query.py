"""Shared task query helpers for gateway and debug APIs."""

from __future__ import annotations

import shlex
from collections.abc import Mapping
from typing import Any, Callable

from mente.task_core.models import Task, TaskStatus


class TaskQueryError(ValueError):
    """Raised when a task query is invalid."""


TaskRepositoryFactory = Callable[[], Any]


def parse_gateway_task_query(raw_args: str, default_session_id: str) -> dict[str, Any]:
    """Parse `/tasks ...` arguments into a normalized query dict."""
    query = {
        "scope": "session",
        "session_id": default_session_id,
        "source": None,
        "status": None,
        "task_type": None,
        "limit": 6,
        "offset": 0,
        "help": False,
        "error": None,
    }
    raw_args = (raw_args or "").strip()
    if not raw_args:
        return query

    try:
        tokens = shlex.split(raw_args)
    except ValueError as exc:
        query["error"] = f"Invalid /tasks arguments: {exc}"
        return query

    try:
        return _parse_task_query_tokens(
            tokens,
            default_scope="session",
            default_session_id=default_session_id,
            default_limit=6,
            allow_help=True,
        )
    except TaskQueryError as exc:
        query["error"] = str(exc)
        return query


def parse_http_task_query(params: Mapping[str, str]) -> dict[str, Any]:
    """Parse HTTP query parameters for the debug tasks API."""
    return _parse_task_query_tokens(
        [],
        default_scope="recent",
        default_session_id=None,
        default_limit=20,
        allow_help=False,
        params=params,
    )


def execute_task_query(query: dict[str, Any], repository_factory: TaskRepositoryFactory) -> dict[str, Any]:
    """Run a normalized task query against a repository and return a page."""
    requested_limit = query["limit"]
    requested_offset = query["offset"]
    fetch_limit = requested_limit + 1
    repo = repository_factory()
    try:
        if query["scope"] == "recent":
            records = repo.list_recent(
                limit=fetch_limit,
                offset=requested_offset,
                source=query["source"],
                status=query["status"],
                task_type=query["task_type"],
            )
        else:
            records = repo.list_by_session(
                query["session_id"],
                limit=fetch_limit,
                offset=requested_offset,
                source=query["source"],
                status=query["status"],
                task_type=query["task_type"],
            )
    finally:
        try:
            repo.close()
        except Exception:
            pass

    has_more = len(records) > requested_limit
    tasks = records[:requested_limit]
    next_offset = requested_offset + len(tasks) if has_more else None
    return {
        "tasks": tasks,
        "count": len(tasks),
        "pagination": {
            "limit": requested_limit,
            "offset": requested_offset,
            "returned": len(tasks),
            "has_more": has_more,
            "next_offset": next_offset,
            "next_cursor": str(next_offset) if next_offset is not None else None,
        },
    }


def serialize_task_query(query: dict[str, Any]) -> dict[str, Any]:
    """Convert a normalized task query into JSON-safe output."""
    return {
        "scope": query["scope"],
        "session_id": query["session_id"],
        "source": query["source"],
        "status": query["status"],
        "task_type": query["task_type"],
        "limit": query["limit"],
        "offset": query["offset"],
    }


def serialize_task(task: Task) -> dict[str, Any]:
    """Convert a task into JSON-safe output for debug surfaces."""
    payload = task.model_dump(mode="json")
    payload["status"] = task.status.value
    payload["source"] = str(task.metadata.get("source") or "unknown")
    return payload


def _parse_task_query_tokens(
    tokens: list[str],
    *,
    default_scope: str,
    default_session_id: str | None,
    default_limit: int,
    allow_help: bool,
    params: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    query = {
        "scope": default_scope,
        "session_id": default_session_id,
        "source": None,
        "status": None,
        "task_type": None,
        "limit": default_limit,
        "offset": 0,
        "help": False,
        "error": None,
    }

    for token in tokens:
        lower = token.lower()
        if allow_help and lower in {"help", "-h", "--help"}:
            query["help"] = True
            continue
        if lower in {"recent", "all"}:
            query["scope"] = "recent"
            continue
        if lower == "session":
            query["scope"] = "session"
            continue
        if "=" not in token:
            raise TaskQueryError(
                "Unknown /tasks filter. Use `recent`, `session`, `source=...`, "
                "`status=...`, `task_type=...`, `session_id=...`, or `limit=...`."
            )
        key, value = token.split("=", 1)
        _apply_query_pair(query, key, value, token=token)

    if params:
        for key, value in params.items():
            _apply_query_pair(query, key, value, token=f"{key}={value}")

    if query["scope"] == "session" and not query["session_id"]:
        raise TaskQueryError("Session scope requires `session_id=<id>`.")

    return query


def _apply_query_pair(query: dict[str, Any], key: str, value: str | None, *, token: str) -> None:
    lower_key = key.strip().lower()
    if lower_key in {"scope"}:
        normalized = (value or "").strip().lower()
        if normalized in {"recent", "all"}:
            query["scope"] = "recent"
            return
        if normalized == "session":
            query["scope"] = "session"
            return
        raise TaskQueryError("Invalid scope. Use `scope=recent` or `scope=session`.")

    if "=" not in token:
        raise TaskQueryError(
            "Unknown /tasks filter. Use `recent`, `session`, `source=...`, "
            "`status=...`, `task_type=...`, `session_id=...`, or `limit=...`."
        )

    raw_value = (value or "").strip()
    if lower_key == "limit":
        if not raw_value.isdigit():
            raise TaskQueryError("Invalid limit. Use `limit=<positive integer>`.")
        query["limit"] = max(1, min(int(raw_value), 50))
        return

    if lower_key in {"offset", "cursor"}:
        if not raw_value.isdigit():
            raise TaskQueryError(f"Invalid {lower_key}. Use `{lower_key}=<non-negative integer>`.")
        query["offset"] = int(raw_value)
        return

    if lower_key == "source":
        source = raw_value.lower()
        if source not in {"gateway", "cron"}:
            raise TaskQueryError("Invalid source. Use `source=gateway` or `source=cron`.")
        query["source"] = source
        return

    if lower_key == "status":
        status = raw_value.lower()
        if status not in TaskStatus._value2member_map_:
            valid_statuses = ", ".join(task_status.value for task_status in TaskStatus)
            raise TaskQueryError(f"Invalid status. Use one of: `{valid_statuses}`.")
        query["status"] = status
        return

    if lower_key == "task_type":
        if not raw_value:
            raise TaskQueryError("Invalid task_type. Use `task_type=<name>`.")
        query["task_type"] = raw_value
        return

    if lower_key in {"session_id", "session"}:
        if not raw_value:
            raise TaskQueryError("Invalid session filter. Use `session_id=<id>`.")
        query["scope"] = "session"
        query["session_id"] = raw_value
        return

    raise TaskQueryError(
        "Unknown /tasks filter. Use `recent`, `session`, `source=...`, "
        "`status=...`, `task_type=...`, `session_id=...`, `offset=...`, or `limit=...`."
    )
