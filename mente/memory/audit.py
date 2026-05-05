"""Helpers for building operator-facing memory audit payloads."""

from __future__ import annotations

from mente.memory.models import MemoryAuditPayload, MemoryBuildTrace, MemoryPromotionTrace


def build_memory_audit_payload(
    trace: MemoryBuildTrace,
    promotion_trace: MemoryPromotionTrace | None = None,
) -> MemoryAuditPayload:
    """Build a compact post-run audit payload from selection and promotion traces."""

    promotion_trace = promotion_trace or MemoryPromotionTrace()
    return MemoryAuditPayload(
        policy_id=trace.policy_id,
        selected=list(trace.selected),
        skipped=list(trace.skipped),
        promoted=list(promotion_trace.promoted),
        rejected=list(promotion_trace.rejected),
    )
