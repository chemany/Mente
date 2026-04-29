"""Deterministic memory promotion for Mente."""

from __future__ import annotations

from mente.memory.models import MemoryRecord
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

    def extract(self, task: Task, result: ExecutionResult) -> list[MemoryRecord]:
        """Extract deterministic memory records from an execution result."""
        source = str(task.metadata.get("source") or "")
        is_conversation_session_source = (
            task.task_type == "conversation" and source in {"gateway", "api_server"}
        )
        scope = "session" if is_conversation_session_source else "task_type"
        policy = self.memory_policy_resolver.resolve(task)
        max_promoted = min(self.max_promoted_memories_per_run, policy.max_promoted_memories)

        promoted: list[MemoryRecord] = []
        seen: set[str] = set()
        for index, candidate in enumerate(result.memory_candidates):
            fact = truncate_for_policy(
                self.normalize_fact(candidate),
                policy.max_chars_per_promoted_fact,
            )
            if not fact or fact in seen:
                continue
            seen.add(fact)
            promoted.append(
                MemoryRecord(
                    memory_id=f"{task.task_id}:memory:{len(promoted)}",
                    session_id=task.session_id if scope == "session" else None,
                    task_id=task.task_id,
                    task_type=task.task_type,
                    source=source,
                    scope=scope,
                    fact=fact,
                    metadata={"promotion_reason": "executor_memory_candidate"},
                )
            )
            if len(promoted) >= max_promoted:
                break
        return promoted

    def persist(
        self,
        task: Task,
        result: ExecutionResult,
        repository: MemoryRepository,
    ) -> list[MemoryRecord]:
        """Persist promoted memories and return them."""
        promoted = self.extract(task, result)
        for record in promoted:
            repository.save(record)
        return promoted
