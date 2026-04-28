"""Task orchestration service for Mente."""

from __future__ import annotations

import logging

from mente.context_builder.builder import ContextBuilder
from mente.executors.base import Executor
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
    ) -> None:
        self.repository = repository
        self.context_builder = context_builder
        self.executor = executor

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
