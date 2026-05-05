"""Small shared execution-event helpers for Mente runtime progress."""

from __future__ import annotations

import logging
from typing import Any, Callable


ExecutionEventCallback = Callable[[str, dict[str, Any]], None]


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
