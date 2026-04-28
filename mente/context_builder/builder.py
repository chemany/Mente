"""Deterministic execution request builder for Mente."""

from __future__ import annotations

from mente.memory.models import MemoryBuildTrace, MemoryTraceItem
from mente.memory.repository import MemoryRepository
from mente.task_core.models import ExecutionRequest, Task


class ContextBuilder:
    """Convert normalized tasks into executor-ready requests."""

    def __init__(
        self,
        default_workspace: str = ".",
        memory_repository: MemoryRepository | None = None,
        memory_limit: int = 5,
    ) -> None:
        self.default_workspace = default_workspace
        self.memory_repository = memory_repository
        self.memory_limit = memory_limit

    def build(self, task: Task) -> ExecutionRequest:
        """Build a stable execution request from a task."""
        request, _trace = self.build_with_trace(task)
        return request

    def build_with_trace(self, task: Task) -> tuple[ExecutionRequest, MemoryBuildTrace]:
        """Build a stable execution request and memory diagnostics."""
        memory_facts, trace = self._build_memory_facts(task)
        return ExecutionRequest(
            task_id=task.task_id,
            session_id=task.session_id,
            task_type=task.task_type,
            objective=task.objective,
            user_request=task.user_request,
            workspace=task.workspace or self.default_workspace,
            constraints=list(task.constraints),
            allowed_tools=list(task.allowed_tools),
            memory_facts=memory_facts,
            skill_refs=list(task.skill_refs),
            artifacts_in=list(task.artifacts_in),
            acceptance_criteria=list(task.acceptance_criteria),
            budget=dict(task.budget),
            execution_mode=task.execution_mode,
            resume_token=task.resume_token,
            metadata=dict(task.metadata),
        ), trace

    def _build_memory_facts(self, task: Task) -> tuple[list[str], MemoryBuildTrace]:
        task_memory_facts = list(task.memory_facts)
        trace = MemoryBuildTrace()
        if self.memory_repository is None or self.memory_limit <= 0:
            return task_memory_facts, trace

        retrieved = self.memory_repository.list_relevant(
            session_id=task.session_id,
            task_type=task.task_type,
            limit=self.memory_limit,
        )
        trace.retrieved_count = len(retrieved)
        existing = set(task_memory_facts)
        memory_facts: list[str] = []
        for record in retrieved:
            prompt_fact = f"Memory: {record.fact}"
            if record.fact in existing or prompt_fact in existing:
                trace.skipped.append(
                    MemoryTraceItem(
                        memory_id=record.memory_id,
                        scope=record.scope,
                        fact=record.fact,
                        reason="duplicate_existing_fact",
                    )
                )
                continue

            if len(memory_facts) >= self.memory_limit:
                trace.skipped.append(
                    MemoryTraceItem(
                        memory_id=record.memory_id,
                        scope=record.scope,
                        fact=record.fact,
                        reason="memory_limit_reached",
                    )
                )
                continue

            memory_facts.append(prompt_fact)
            existing.add(prompt_fact)
            trace.selected.append(
                MemoryTraceItem(
                    memory_id=record.memory_id,
                    scope=record.scope,
                    fact=record.fact,
                    reason="scope_match",
                )
            )

        trace.injected_count = len(trace.selected)
        memory_facts.extend(task_memory_facts)
        return memory_facts, trace
