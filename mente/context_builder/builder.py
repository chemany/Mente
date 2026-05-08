"""Deterministic execution request builder for Mente."""

from __future__ import annotations

from collections.abc import Mapping

from mente.memory.models import MemoryBuildTrace
from mente.memory.policy import MemoryPolicyResolver
from mente.memory.repository import MemoryRepository
from mente.memory.context import resolve_memory_context, resolve_memory_read_mode, uses_on_demand_memory
from mente.task_core.models import ExecutionRequest, Task


class ContextBuilder:
    """Convert normalized tasks into executor-ready requests."""

    def __init__(
        self,
        default_workspace: str = ".",
        memory_repository: MemoryRepository | None = None,
        memory_limit: int = 5,
        memory_policy_resolver: MemoryPolicyResolver | None = None,
    ) -> None:
        self.default_workspace = default_workspace
        self.memory_repository = memory_repository
        self.memory_limit = memory_limit
        self.memory_policy_resolver = memory_policy_resolver or MemoryPolicyResolver.default()

    def build(self, task: Task) -> ExecutionRequest:
        """Build a stable execution request from a task."""
        request, _trace = self.build_with_trace(task)
        return request

    def build_with_trace(self, task: Task) -> tuple[ExecutionRequest, MemoryBuildTrace]:
        """Build a stable execution request and memory diagnostics."""
        memory_facts, trace = resolve_memory_context(
            task,
            memory_repository=self.memory_repository,
            memory_limit=self.memory_limit,
            memory_policy_resolver=self.memory_policy_resolver,
        )
        request_memory_facts = memory_facts
        memory_read_mode = resolve_memory_read_mode(task)
        if uses_on_demand_memory(task):
            request_memory_facts = list(task.memory_facts)
            trace.injected_count = 0
            trace.prompt_budget_char_count = 0
        metadata = dict(task.metadata)
        metadata["memory_context_prepared"] = True
        metadata["memory_read_mode"] = memory_read_mode
        return ExecutionRequest(
            task_id=task.task_id,
            session_id=task.session_id,
            task_type=task.task_type,
            objective=task.objective,
            user_request=task.user_request,
            workspace=task.workspace or self.default_workspace,
            constraints=list(task.constraints),
            allowed_tools=list(task.allowed_tools),
            memory_facts=request_memory_facts,
            skill_refs=list(task.skill_refs),
            artifacts_in=list(task.artifacts_in),
            acceptance_criteria=list(task.acceptance_criteria),
            budget=dict(task.budget),
            execution_mode=task.execution_mode,
            execution_session=task.execution_session,
            resume_token=task.resume_token,
            metadata=metadata,
        ), trace
