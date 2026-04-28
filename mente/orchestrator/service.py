"""Task orchestration service for Mente."""

from __future__ import annotations

import logging

from mente.context_builder.builder import ContextBuilder
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

        request = self.context_builder.build(task)
        task.status = TaskStatus.CONTEXT_PREPARED
        self.repository.save(task)

        task.status = TaskStatus.EXECUTING
        self.repository.save(task)
        result = self.executor.execute(request)
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

    def _persist_promoted_memory(self, task: Task, result: ExecutionResult) -> None:
        if self.memory_repository is None or self.memory_promoter is None:
            return

        try:
            promoted = self.memory_promoter.persist(task, result, self.memory_repository)
        except Exception:
            logger.exception("failed to persist promoted memory for task %s", task.task_id)
            result.metadata["promoted_memory_count"] = 0
            return

        result.metadata["promoted_memory_count"] = len(promoted)
