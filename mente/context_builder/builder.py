"""Deterministic execution request builder for Mente."""

from __future__ import annotations

from collections.abc import Mapping

from mente.memory.models import MemoryBuildTrace
from mente.memory.policy import MemoryPolicyResolver
from mente.memory.repository import MemoryRepository
from mente.memory.context import (
    resolve_memory_context,
    resolve_memory_read_mode,
    retain_on_demand_prompt_memories,
    uses_on_demand_memory,
)
from mente.mente_inventory import build_worker_mente_inventory_payload
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
            task_memory_facts = list(task.memory_facts)
            request_memory_facts, retained_char_count = retain_on_demand_prompt_memories(
                memory_facts=memory_facts,
                trace=trace,
                task_memory_facts=task_memory_facts,
            )
            trace.injected_count = max(0, len(request_memory_facts) - len(task_memory_facts))
            trace.prompt_budget_char_count = retained_char_count
        metadata = dict(task.metadata)
        inventory_payload = build_worker_mente_inventory_payload(task)
        if inventory_payload is not None:
            inventory_fact, inventory_metadata = inventory_payload
            if inventory_fact and not any(
                fact.startswith("Mente inventory:") for fact in request_memory_facts
            ):
                request_memory_facts = [*request_memory_facts, inventory_fact]
            metadata.setdefault("mente_inventory", inventory_metadata)
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
            parent_task_id=task.parent_task_id,
            job_id=task.job_id,
            role=task.role,
            dispatch_mode=task.dispatch_mode,
            worker_lane=task.worker_lane,
            worker_skill_refs=list(task.worker_skill_refs),
            execution_mode=task.execution_mode,
            execution_session=task.execution_session,
            resume_token=task.resume_token,
            metadata=metadata,
        ), trace
