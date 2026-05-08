"""Deterministic memory promotion for Mente."""

from __future__ import annotations

from mente.memory.models import MemoryPromotionTrace, MemoryPromotionTraceItem, MemoryRecord
from mente.memory.policy import MemoryPolicyResolver, truncate_for_policy
from mente.memory.repository import MemoryRepository
from mente.task_core.models import ExecutionResult, Task


class MemoryPromoter:
    """Convert executor memory candidates into stable memory records."""

    def __init__(
        self,
        max_promoted_memories_per_run: int = 5,
        memory_policy_resolver: MemoryPolicyResolver | None = None,
    ) -> None:
        self.max_promoted_memories_per_run = max_promoted_memories_per_run
        self.memory_policy_resolver = memory_policy_resolver or MemoryPolicyResolver.default()

    def normalize_fact(self, text: str) -> str:
        """Normalize a candidate into a prompt-safe fact string."""
        lines = [line.strip() for line in text.strip().splitlines() if line.strip()]
        return "\n".join(lines)

    def extract_with_trace(
        self,
        task: Task,
        result: ExecutionResult,
    ) -> tuple[list[MemoryRecord], MemoryPromotionTrace]:
        """Extract deterministic memory records and audit decisions."""
        source = str(task.metadata.get("source") or "")
        is_conversation_session_source = (
            task.task_type == "conversation" and source in {"gateway", "api_server", "tui"}
        )
        scope = "session" if is_conversation_session_source else "task_type"
        policy = self.memory_policy_resolver.resolve(task)
        max_promoted = min(self.max_promoted_memories_per_run, policy.max_promoted_memories)

        promoted: list[MemoryRecord] = []
        trace = MemoryPromotionTrace()
        seen: set[str] = set()
        for candidate in result.memory_candidates:
            normalized = self.normalize_fact(candidate)
            fact = truncate_for_policy(
                normalized,
                policy.max_chars_per_promoted_fact,
            )
            if not fact:
                trace.rejected.append(
                    MemoryPromotionTraceItem(
                        fact=normalized,
                        reason="empty_candidate",
                    )
                )
                continue
            if fact in seen:
                trace.rejected.append(
                    MemoryPromotionTraceItem(
                        fact=fact,
                        reason="duplicate_candidate",
                    )
                )
                continue
            if len(promoted) >= max_promoted:
                trace.rejected.append(
                    MemoryPromotionTraceItem(
                        fact=fact,
                        reason="promotion_limit_reached",
                    )
                )
                continue

            seen.add(fact)
            record = MemoryRecord(
                memory_id=f"{task.task_id}:memory:{len(promoted)}",
                session_id=task.session_id if scope == "session" else None,
                task_id=task.task_id,
                task_type=task.task_type,
                source=source,
                scope=scope,
                fact=fact,
                metadata={"promotion_reason": "executor_memory_candidate"},
            )
            promoted.append(record)
            trace.promoted.append(
                MemoryPromotionTraceItem(
                    memory_id=record.memory_id,
                    scope=record.scope,
                    fact=record.fact,
                    reason="executor_memory_candidate",
                )
            )
        return promoted, trace

    def extract(self, task: Task, result: ExecutionResult) -> list[MemoryRecord]:
        """Extract deterministic memory records from an execution result."""
        promoted, _trace = self.extract_with_trace(task, result)
        return promoted

    def persist_with_trace(
        self,
        task: Task,
        result: ExecutionResult,
        repository: MemoryRepository,
    ) -> tuple[list[MemoryRecord], MemoryPromotionTrace]:
        """Persist promoted memories and return both records and audit details."""
        candidates, extraction_trace = self.extract_with_trace(task, result)
        promoted: list[MemoryRecord] = []
        trace = MemoryPromotionTrace(rejected=list(extraction_trace.rejected))
        for record in candidates:
            stored_record, write_reason = repository.save_resolved_fact(record)
            if write_reason == "duplicate_existing":
                trace.rejected.append(
                    MemoryPromotionTraceItem(
                        fact=record.fact,
                        reason="duplicate_existing",
                        memory_id=stored_record.memory_id,
                        scope=stored_record.scope,
                    )
                )
                continue
            promoted.append(stored_record)
            trace.promoted.append(
                MemoryPromotionTraceItem(
                    memory_id=stored_record.memory_id,
                    scope=stored_record.scope,
                    fact=stored_record.fact,
                    reason="executor_memory_candidate",
                )
            )
        return promoted, trace

    def persist(
        self,
        task: Task,
        result: ExecutionResult,
        repository: MemoryRepository,
    ) -> list[MemoryRecord]:
        """Persist promoted memories and return them."""
        promoted, _trace = self.persist_with_trace(task, result, repository)
        return promoted
