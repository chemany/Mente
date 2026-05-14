"""Task orchestration service for Mente."""

from __future__ import annotations

import logging
from typing import Any

from mente.context_builder.builder import ContextBuilder
from mente.memory.audit import build_memory_audit_payload
from mente.memory.models import MemoryBuildTrace, MemoryPromotionTrace
from mente.executors.base import Executor
from mente.feature_flags import review_capability_gate
from mente.memory.promoter import MemoryPromoter
from mente.memory.repository import MemoryRepository
from mente.review.llm_memory_review import build_llm_memory_review_artifact
from mente.review.memory_review import build_memory_review_artifact
from mente.review.session_synthesis import build_session_synthesis_artifact
from mente.review.skill_review import build_skill_review_artifact
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
        result.metadata["task_id"] = task.task_id
        self._persist_execution_session_metadata(task, result)
        self._persist_tool_policy_metadata(task, request.tool_policy)
        self._persist_tool_policy_metadata(result, request.tool_policy)
        self._persist_memory_context(result, trace)
        self._persist_memory_policy(result, trace, task)
        promotion_trace = self._persist_promoted_memory(task, result)
        self._persist_memory_audit(task, result, trace, promotion_trace)
        self._persist_memory_review_artifact(task, result)
        self._persist_llm_memory_review_artifact(task, result)
        self._persist_skill_review_artifact(task, result)
        self._persist_session_synthesis_artifact(task, result)

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

    def _persist_execution_session_metadata(
        self,
        task: Task,
        result: ExecutionResult,
    ) -> None:
        try:
            payload = result.metadata.get("execution_session")
            if isinstance(payload, dict):
                task.metadata["execution_session"] = dict(payload)
        except Exception:
            logger.exception("failed to serialize execution session diagnostics for task %s", task.task_id)

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

    def _persist_promoted_memory(
        self,
        task: Task,
        result: ExecutionResult,
    ) -> MemoryPromotionTrace:
        if self.memory_promoter is None:
            return MemoryPromotionTrace()

        summary: dict[str, Any] = {
            "candidate_count": len(result.memory_candidates),
            "promoted_count": 0,
            "promoted_memory_ids": [],
        }

        if self.memory_repository is None:
            result.metadata["promoted_memory_count"] = 0
            self._persist_memory_promotion(task, result, summary)
            return MemoryPromotionTrace()

        try:
            promoted, trace = self.memory_promoter.persist_with_trace(
                task,
                result,
                self.memory_repository,
            )
        except Exception:
            logger.exception("failed to persist promoted memory for task %s", task.task_id)
            result.metadata["promoted_memory_count"] = 0
            self._persist_memory_promotion(task, result, summary)
            return MemoryPromotionTrace()

        summary["promoted_count"] = len(promoted)
        summary["promoted_memory_ids"] = [record.memory_id for record in promoted]
        result.metadata["promoted_memory_count"] = len(promoted)
        self._persist_memory_promotion(task, result, summary)
        return trace

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

    def _persist_memory_audit(
        self,
        task: Task,
        result: ExecutionResult,
        trace: MemoryBuildTrace,
        promotion_trace: MemoryPromotionTrace,
    ) -> None:
        try:
            audit = build_memory_audit_payload(trace, promotion_trace).model_dump(mode="json")
            task.metadata["memory_audit"] = audit
            result.metadata["memory_audit"] = audit
        except Exception:
            logger.exception("failed to serialize memory audit diagnostics for task %s", task.task_id)

    def _persist_memory_review_artifact(
        self,
        task: Task,
        result: ExecutionResult,
    ) -> None:
        try:
            artifact = build_memory_review_artifact(task, result)
            task.metadata["memory_review_artifact"] = artifact
            result.metadata["memory_review_artifact"] = artifact
        except Exception:
            logger.exception("failed to serialize memory review artifact for task %s", task.task_id)

    def _persist_llm_memory_review_artifact(
        self,
        task: Task,
        result: ExecutionResult,
    ) -> None:
        source = str(task.metadata.get("source") or "").strip()
        workflow_gate, _ = review_capability_gate(
            source=source,
            task_type=task.task_type,
            metadata=task.metadata,
            capability="llm_memory_review",
        )
        if workflow_gate is not True:
            return
        try:
            artifact = build_llm_memory_review_artifact(task, result)
            task.metadata["llm_memory_review_artifact"] = artifact
            result.metadata["llm_memory_review_artifact"] = artifact
        except Exception:
            logger.exception("failed to serialize LLM memory review artifact for task %s", task.task_id)

    def _persist_skill_review_artifact(
        self,
        task: Task,
        result: ExecutionResult,
    ) -> None:
        try:
            artifact = build_skill_review_artifact(task, result)
            task.metadata["skill_review_artifact"] = artifact
            result.metadata["skill_review_artifact"] = artifact
        except Exception:
            logger.exception("failed to serialize skill review artifact for task %s", task.task_id)

    def _persist_session_synthesis_artifact(
        self,
        task: Task,
        result: ExecutionResult,
    ) -> None:
        source = str(task.metadata.get("source") or "").strip()
        workflow_gate, _ = review_capability_gate(
            source=source,
            task_type=task.task_type,
            metadata=task.metadata,
            capability="session_synthesis",
        )
        if workflow_gate is not True:
            return
        try:
            artifact = build_session_synthesis_artifact(task, result)
            task.metadata["session_synthesis_artifact"] = artifact
            result.metadata["session_synthesis_artifact"] = artifact
        except Exception:
            logger.exception(
                "failed to serialize session synthesis artifact for task %s",
                task.task_id,
            )
