"""Task orchestration service for Mente."""

from __future__ import annotations

import logging
from typing import Any

from mente.context_builder.builder import ContextBuilder
from mente.memory.models import MemoryBuildTrace
from mente.executors.base import Executor
from mente.memory.promoter import MemoryPromoter
from mente.memory.repository import MemoryRepository
from mente.task_core.models import ExecutionResult, Task, TaskStatus
from mente.task_core.repository import TaskRepository

logger = logging.getLogger(__name__)


class Orchestrator:
    """Drive tasks through the Phase 1 execution lifecycle."""

    def __init__(
        self,
        repository: TaskRepository,
        context_builder: ContextBuilder,
        executor: Executor,
        memory_repository: MemoryRepository | None = None,
        memory_promoter: MemoryPromoter | None = None,
    ) -> None:
        self.repository = repository
        self.context_builder = context_builder
        self.executor = executor
        self.memory_repository = memory_repository
        self.memory_promoter = memory_promoter

    def run(self, task: Task) -> ExecutionResult:
        """Persist, prepare, execute, and finalize a task."""
        logger.info("starting task %s with status %s", task.task_id, task.status.value)
        self.repository.save(task)

        task.status = TaskStatus.PLANNED
        self.repository.save(task)

        request, trace = self.context_builder.build_with_trace(task)
        self._persist_tool_policy_on_request(task, request)
        self._persist_memory_context(task, trace)
        self._persist_memory_policy(task, trace)
        task.status = TaskStatus.CONTEXT_PREPARED
        self.repository.save(task)

        task.status = TaskStatus.EXECUTING
        self.repository.save(task)
        result = self.executor.execute(request)
        self._persist_tool_policy_metadata(task, request.tool_policy)
        self._persist_tool_policy_metadata(result, request.tool_policy)
        self._persist_memory_context(result, trace)
        self._persist_memory_policy(result, trace, task)
        self._persist_promoted_memory(task, result)

        task.status = TaskStatus.PERSISTED
        self.repository.save(task)

        if result.status == "success":
            task.status = TaskStatus.SUCCEEDED
        elif result.status == "blocked":
            task.status = TaskStatus.BLOCKED
        else:
            task.status = TaskStatus.FAILED
        self.repository.save(task)
        logger.info(
            "finished task %s with executor result %s and final task status %s",
            task.task_id,
            result.status,
            task.status.value,
        )

        return result

    def _persist_tool_policy_on_request(self, task: Task, request) -> None:
        try:
            if request.tool_policy is None:
                policy = task.metadata.get("tool_policy")
                if isinstance(policy, dict):
                    request.tool_policy = dict(policy)
        except Exception:
            logger.exception("failed to thread tool policy onto execution request")

    def _persist_tool_policy_metadata(
        self,
        target: Task | ExecutionResult,
        tool_policy: dict[str, Any] | None,
    ) -> None:
        if tool_policy is None:
            return

        try:
            target.metadata["tool_policy"] = dict(tool_policy)
        except Exception:
            logger.exception("failed to serialize tool policy diagnostics")

    def _persist_memory_context(
        self,
        target: Task | ExecutionResult,
        trace: MemoryBuildTrace,
    ) -> None:
        try:
            target.metadata["memory_context"] = trace.model_dump(mode="json")
        except Exception:
            logger.exception("failed to serialize memory context diagnostics")

    def _persist_memory_policy(
        self,
        target: Task | ExecutionResult,
        trace: MemoryBuildTrace,
        task: Task | None = None,
    ) -> None:
        if not trace.policy_id:
            return

        source_task = task or target
        try:
            policy = self.context_builder.memory_policy_resolver.resolve(source_task)
            target.metadata["memory_policy"] = {
                "policy_id": policy.policy_id,
                "max_injected_memories": policy.max_injected_memories,
                "max_total_injected_chars": policy.max_total_injected_chars,
                "max_promoted_memories": policy.max_promoted_memories,
            }
        except Exception:
            logger.exception("failed to serialize memory policy diagnostics")

    def _persist_promoted_memory(self, task: Task, result: ExecutionResult) -> None:
        if self.memory_promoter is None:
            return

        summary: dict[str, Any] = {
            "candidate_count": len(result.memory_candidates),
            "promoted_count": 0,
            "promoted_memory_ids": [],
        }

        if self.memory_repository is None:
            result.metadata["promoted_memory_count"] = 0
            self._persist_memory_promotion(task, result, summary)
            return

        try:
            promoted = self.memory_promoter.persist(task, result, self.memory_repository)
        except Exception:
            logger.exception("failed to persist promoted memory for task %s", task.task_id)
            result.metadata["promoted_memory_count"] = 0
            self._persist_memory_promotion(task, result, summary)
            return

        summary["promoted_count"] = len(promoted)
        summary["promoted_memory_ids"] = [record.memory_id for record in promoted]
        result.metadata["promoted_memory_count"] = len(promoted)
        self._persist_memory_promotion(task, result, summary)

    def _persist_memory_promotion(
        self,
        task: Task,
        result: ExecutionResult,
        summary: dict[str, Any],
    ) -> None:
        try:
            task.metadata["memory_promotion"] = dict(summary)
            result.metadata["memory_promotion"] = dict(summary)
        except Exception:
            logger.exception("failed to serialize memory promotion diagnostics for task %s", task.task_id)
