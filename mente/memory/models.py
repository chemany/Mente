"""Memory schemas for Mente."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, model_serializer


class MemoryRecord(BaseModel):
    """Stable fact record stored in Mente memory."""

    memory_id: str
    session_id: str | None = None
    task_id: str
    task_type: str
    source: str
    scope: str
    fact: str
    fact_key: str | None = None
    slot_key: str | None = None
    active: bool = True
    superseded_by_memory_id: str | None = None
    kind: str = "fact"
    score: float = 1.0
    created_at: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class MemoryTraceItem(BaseModel):
    """Deterministic trace item for memory retrieval diagnostics."""

    memory_id: str
    scope: str
    kind: str | None = None
    fact: str
    reason: str

    @model_serializer(mode="wrap")
    def _serialize(self, handler):
        payload = handler(self)
        if payload.get("kind") is None:
            payload.pop("kind", None)
        return payload


class MemoryBuildTrace(BaseModel):
    """Compact trace of memory retrieval and injection decisions."""

    retrieved_count: int = 0
    injected_count: int = 0
    policy_id: str | None = None
    prompt_budget_char_count: int = 0
    selected: list[MemoryTraceItem] = Field(default_factory=list)
    skipped: list[MemoryTraceItem] = Field(default_factory=list)


class MemoryPromotionTraceItem(BaseModel):
    """Compact trace item for a promotion decision."""

    fact: str
    reason: str
    memory_id: str | None = None
    scope: str | None = None


class MemoryPromotionTrace(BaseModel):
    """Compact trace of memory promotion decisions."""

    promoted: list[MemoryPromotionTraceItem] = Field(default_factory=list)
    rejected: list[MemoryPromotionTraceItem] = Field(default_factory=list)


class MemoryAuditPayload(BaseModel):
    """Operator-facing audit view for memory selection and promotion."""

    policy_id: str | None = None
    selected: list[MemoryTraceItem] = Field(default_factory=list)
    skipped: list[MemoryTraceItem] = Field(default_factory=list)
    promoted: list[MemoryPromotionTraceItem] = Field(default_factory=list)
    rejected: list[MemoryPromotionTraceItem] = Field(default_factory=list)
