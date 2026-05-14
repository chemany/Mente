"""Shared memory query helpers for gateway and debug APIs."""

from __future__ import annotations

from collections.abc import Mapping
import inspect
from typing import Any, Callable

from mente.memory.models import MemoryRecord


class MemoryQueryError(ValueError):
    """Raised when a memory query is invalid."""


MemoryRepositoryFactory = Callable[[], Any]


def parse_http_memory_query(params: Mapping[str, str]) -> dict[str, Any]:
    """Parse HTTP query parameters for the debug memories API."""
    query: dict[str, Any] = {
        "scope": "recent",
        "session_id": None,
        "source": None,
        "task_type": None,
        "memory_scope": None,
        "include_superseded": False,
        "limit": 20,
        "offset": 0,
    }

    for key, value in params.items():
        _apply_query_pair(query, key, value)

    if query["scope"] == "session" and not query["session_id"]:
        raise MemoryQueryError("Session scope requires `session_id=<id>`.")

    return query


def execute_memory_query(
    query: dict[str, Any],
    repository_factory: MemoryRepositoryFactory,
) -> dict[str, Any]:
    """Run a normalized memory query against a repository and return a page."""
    requested_limit = query["limit"]
    requested_offset = query["offset"]
    fetch_limit = requested_limit + 1
    repo = repository_factory()
    try:
        if query["scope"] == "recent":
            records = _call_memory_list_method(
                repo.list_recent,
                limit=fetch_limit,
                offset=requested_offset,
                source=query["source"],
                task_type=query["task_type"],
                memory_scope=query["memory_scope"],
                include_inactive=query["include_superseded"],
            )
        else:
            records = _call_memory_list_method(
                repo.list_by_session,
                query["session_id"],
                limit=fetch_limit,
                offset=requested_offset,
                source=query["source"],
                task_type=query["task_type"],
                memory_scope=query["memory_scope"],
                include_inactive=query["include_superseded"],
            )
    finally:
        try:
            repo.close()
        except Exception:
            pass

    has_more = len(records) > requested_limit
    memories = records[:requested_limit]
    next_offset = requested_offset + len(memories) if has_more else None
    return {
        "memories": memories,
        "count": len(memories),
        "pagination": {
            "limit": requested_limit,
            "offset": requested_offset,
            "returned": len(memories),
            "has_more": has_more,
            "next_offset": next_offset,
            "next_cursor": str(next_offset) if next_offset is not None else None,
        },
    }


def _call_memory_list_method(method: Callable[..., list[MemoryRecord]], *args: Any, **kwargs: Any) -> list[MemoryRecord]:
    """Call memory repositories that may predate the include_inactive debug flag."""
    try:
        parameters = inspect.signature(method).parameters
    except (TypeError, ValueError):
        parameters = {}
    if "include_inactive" not in parameters and not any(
        parameter.kind is inspect.Parameter.VAR_KEYWORD for parameter in parameters.values()
    ):
        kwargs.pop("include_inactive", None)
    return method(*args, **kwargs)


def serialize_memory_query(query: dict[str, Any]) -> dict[str, Any]:
    """Convert a normalized memory query into JSON-safe output."""
    return {
        "scope": query["scope"],
        "session_id": query["session_id"],
        "source": query["source"],
        "task_type": query["task_type"],
        "memory_scope": query["memory_scope"],
        "include_superseded": query["include_superseded"],
        "limit": query["limit"],
        "offset": query["offset"],
    }


def serialize_memory(record: MemoryRecord) -> dict[str, Any]:
    """Convert a memory record into JSON-safe output for debug surfaces."""
    return record.model_dump(mode="json")


def _apply_query_pair(query: dict[str, Any], key: str, value: str | None) -> None:
    lower_key = key.strip().lower()
    raw_value = (value or "").strip()

    if lower_key == "scope":
        normalized = raw_value.lower()
        if normalized in {"recent", "all"}:
            query["scope"] = "recent"
            return
        if normalized == "session":
            query["scope"] = "session"
            return
        raise MemoryQueryError("Invalid scope. Use `scope=recent` or `scope=session`.")

    if lower_key == "limit":
        if not raw_value.isdigit():
            raise MemoryQueryError("Invalid limit. Use `limit=<positive integer>`.")
        query["limit"] = max(1, min(int(raw_value), 50))
        return

    if lower_key in {"offset", "cursor"}:
        if not raw_value.isdigit():
            raise MemoryQueryError(f"Invalid {lower_key}. Use `{lower_key}=<non-negative integer>`.")
        query["offset"] = int(raw_value)
        return

    if lower_key == "source":
        source = raw_value.lower()
        if source not in {"gateway", "cron"}:
            raise MemoryQueryError("Invalid source. Use `source=gateway` or `source=cron`.")
        query["source"] = source
        return

    if lower_key == "task_type":
        if not raw_value:
            raise MemoryQueryError("Invalid task_type. Use `task_type=<name>`.")
        query["task_type"] = raw_value
        return

    if lower_key == "memory_scope":
        normalized_scope = raw_value.lower()
        if normalized_scope not in {"session", "task_type", "global"}:
            raise MemoryQueryError(
                "Invalid memory_scope. Use `memory_scope=session`, `memory_scope=task_type`, or `memory_scope=global`."
            )
        query["memory_scope"] = normalized_scope
        return

    if lower_key == "include_superseded":
        normalized = raw_value.lower()
        if normalized in {"1", "true", "yes", "on"}:
            query["include_superseded"] = True
            return
        if normalized in {"0", "false", "no", "off", ""}:
            query["include_superseded"] = False
            return
        raise MemoryQueryError("Invalid include_superseded. Use `include_superseded=1` or `include_superseded=0`.")

    if lower_key in {"session_id", "session"}:
        if not raw_value:
            raise MemoryQueryError("Invalid session filter. Use `session_id=<id>`.")
        query["scope"] = "session"
        query["session_id"] = raw_value
        return

    raise MemoryQueryError(
        "Unknown memory filter. Use `scope=...`, `session_id=...`, `source=...`, "
        "`task_type=...`, `memory_scope=...`, `include_superseded=...`, `offset=...`, or `limit=...`."
    )
