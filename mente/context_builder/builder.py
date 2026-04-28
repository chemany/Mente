"""Deterministic execution request builder for Mente."""

from __future__ import annotations

from mente.task_core.models import ExecutionRequest, Task


class ContextBuilder:
    """Convert normalized tasks into executor-ready requests."""

    def __init__(self, default_workspace: str = ".") -> None:
        self.default_workspace = default_workspace

    def build(self, task: Task) -> ExecutionRequest:
        """Build a stable execution request from a task."""
        return ExecutionRequest(
            task_id=task.task_id,
            session_id=task.session_id,
            task_type=task.task_type,
            objective=task.objective,
            user_request=task.user_request,
            workspace=task.workspace or self.default_workspace,
            constraints=list(task.constraints),
            allowed_tools=list(task.allowed_tools),
            memory_facts=list(task.memory_facts),
            skill_refs=list(task.skill_refs),
            artifacts_in=list(task.artifacts_in),
            acceptance_criteria=list(task.acceptance_criteria),
            budget=dict(task.budget),
            execution_mode=task.execution_mode,
            resume_token=task.resume_token,
            metadata=dict(task.metadata),
        )
