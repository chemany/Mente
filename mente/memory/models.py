"""Memory schemas for Mente."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class MemoryRecord(BaseModel):
    """Stable fact record stored in Mente memory."""

    memory_id: str
    session_id: str | None = None
    task_id: str
    task_type: str
    source: str
    scope: str
    fact: str
    kind: str = "fact"
    score: float = 1.0
    created_at: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
