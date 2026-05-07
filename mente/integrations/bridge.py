"""Thin Mente task bridge helpers."""

from __future__ import annotations

import json
import os
import uuid
from typing import Any

from pydantic import ValidationError

from mente.execution_events import ExecutionEventCallback
from mente.context_builder.builder import ContextBuilder
from mente.executors import CodexKernelAdapter, resolve_tool_exposure_policy
from mente.executors.base import Executor
from mente.executors.codex import CodexExecutor
from mente.executors.runtime_config import RuntimeConfig, resolve_runtime_config
from mente.feature_flags import (
    build_api_server_conversation_workflow_contract,
    is_remember_intent_direct_write_enabled,
    review_capability_gate,
)
from mente.memory.context import persist_explicit_memory_write
from mente.memory.promoter import MemoryPromoter
from mente.memory.repository import SQLiteMemoryRepository
from mente.orchestrator.service import Orchestrator
from mente.review.memory_review import MemoryReviewWorker
from mente.review.remember_intent import extract_explicit_remember_intent_facts
from mente.review.session_synthesis import SessionSynthesisWorker
from mente.review.skill_review import SkillReviewWorker
from mente.task_core.models import (
    ExecutionMode,
    ExecutionRequest,
    ExecutionResult,
    ExecutionSession,
    Task,
)
from mente.task_core.repository import SQLiteTaskRepository


def _resolve_workspace(workspace: str | None) -> str:
    """Resolve the workspace used for a bridged task."""
    return workspace or os.getenv("TERMINAL_CWD") or os.getcwd()


def _resolve_tool_policy(*, source: str, task_type: str) -> dict[str, object]:
    """Resolve a deterministic Mente-owned tool exposure policy."""
    return resolve_tool_exposure_policy(source=source, task_type=task_type).as_metadata()


def _build_task_repository() -> SQLiteTaskRepository:
    """Create the default persistent task repository."""
    return SQLiteTaskRepository()


def _build_memory_repository() -> SQLiteMemoryRepository:
    """Create the default persistent memory repository."""
    return SQLiteMemoryRepository()


def _resolve_runtime_config_for_workspace(workspace: str) -> RuntimeConfig:
    """Resolve the private runtime config for a Mente workspace."""
    return resolve_runtime_config(workspace)


def _build_kernel_adapter(
    workspace: str,
    runtime_config: RuntimeConfig | None = None,
    memory_repository: SQLiteMemoryRepository | None = None,
    event_callback: ExecutionEventCallback | None = None,
    cancel_event: Any | None = None,
) -> CodexKernelAdapter:
    """Create the default Codex-backed kernel adapter."""
    return CodexExecutor(
        runtime_config=runtime_config or _resolve_runtime_config_for_workspace(workspace),
        memory_repository=memory_repository,
        event_callback=event_callback,
        cancel_event=cancel_event,
    )


def _build_orchestrator(
    workspace: str,
    repository,
    memory_repository: SQLiteMemoryRepository | None = None,
    executor: Executor | None = None,
    event_callback: ExecutionEventCallback | None = None,
    cancel_event: Any | None = None,
) -> Orchestrator:
    """Create the default Phase 2 orchestrator stack."""
    memory_repository = memory_repository or _build_memory_repository()
    return Orchestrator(
        repository=repository,
        context_builder=ContextBuilder(
            default_workspace=workspace,
            memory_repository=memory_repository,
            memory_limit=5,
        ),
        executor=executor
        or _build_kernel_adapter(
            workspace,
            memory_repository=memory_repository,
            event_callback=event_callback,
            cancel_event=cancel_event,
        ),
        memory_repository=memory_repository,
        memory_promoter=MemoryPromoter(),
    )


def _run_task(task: Task) -> ExecutionResult:
    """Run a task through the default Phase 2 runtime and close resources."""
    repository = _build_task_repository()
    memory_repository = _build_memory_repository()
    try:
        return _build_orchestrator(
            task.workspace or ".",
            repository,
            memory_repository,
        ).run(task)
    finally:
        for repo in (memory_repository, repository):
            close = getattr(repo, "close", None)
            if callable(close):
                close()


def _is_unbacked_prior_claim(candidate: str) -> bool:
    """Return True when a candidate claims prior preferences without provided memory."""
    normalized = " ".join(candidate.lower().split())
    return any(
        phrase in normalized
        for phrase in (
            "earlier",
            "previously",
            "previous ",
            "prior ",
            "before",
            "already mentioned",
        )
    )


class _APIServerIsolationExecutor(CodexKernelAdapter):
    """Wrap Codex execution with empty-session isolation for API server turns."""

    def __init__(
        self,
        inner: CodexKernelAdapter | None = None,
        workspace: str | None = None,
        runtime_config: RuntimeConfig | None = None,
        memory_repository: SQLiteMemoryRepository | None = None,
    ) -> None:
        self._inner = inner or _build_kernel_adapter(
            workspace or ".",
            runtime_config=runtime_config,
            memory_repository=memory_repository,
        )

    def build_request_payload(self, request: ExecutionRequest) -> dict[str, object]:
        return self._inner.build_request_payload(request)

    def supports_kernel_sessions(self) -> bool:
        return self._inner.supports_kernel_sessions()

    def execute(self, request: ExecutionRequest) -> ExecutionResult:
        result = self._inner.execute(request)
        if request.memory_facts:
            return result

        result.memory_candidates = [
            candidate
            for candidate in result.memory_candidates
            if not _is_unbacked_prior_claim(candidate)
        ]
        return result


def _normalize_history(history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Strip unstable fields from gateway history before serialization."""
    normalized: list[dict[str, Any]] = []
    for message in history or []:
        if not isinstance(message, dict):
            continue
        entry = {
            key: value
            for key, value in sorted(message.items())
            if key != "timestamp"
        }
        normalized.append(entry)
    return normalized


def _build_conversation_history_fact(history: list[dict[str, Any]]) -> str | None:
    """Serialize conversation history deterministically for task memory facts."""
    if not history:
        return None
    serialized_history = json.dumps(
        _normalize_history(history),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return f"Conversation history (JSON):\n{serialized_history}"


def _normalize_skill_refs(skill_refs: list[str] | tuple[str, ...] | None) -> list[str]:
    """Normalize caller-provided skill refs into a stable list."""
    normalized: list[str] = []
    for raw_ref in skill_refs or ():
        candidate = str(raw_ref).strip()
        if candidate:
            normalized.append(candidate)
    return normalized


def normalize_api_execution_continuity(
    *,
    execution_mode: ExecutionMode | str | None = None,
    execution_session: ExecutionSession | dict[str, Any] | None = None,
) -> tuple[ExecutionMode, ExecutionSession | None]:
    """Normalize one caller continuity request into the canonical bridge contract."""
    normalized_mode = ExecutionMode.STATELESS
    if execution_mode not in (None, ""):
        candidate = str(execution_mode).strip().lower()
        if candidate == "session":
            candidate = ExecutionMode.SESSIONFUL.value
        normalized_mode = ExecutionMode(candidate)

    normalized_session: ExecutionSession | None = None
    if execution_session is not None:
        try:
            normalized_session = ExecutionSession.model_validate(execution_session)
        except ValidationError as exc:
            first_error = exc.errors()[0] if exc.errors() else {}
            msg = str(first_error.get("msg") or str(exc))
            if msg.startswith("Value error, "):
                msg = msg[len("Value error, ") :]
            raise ValueError(msg) from exc
        if execution_mode in (None, ""):
            normalized_mode = ExecutionMode.SESSIONFUL

    if normalized_mode is ExecutionMode.STATELESS and normalized_session is not None:
        msg = "execution_session is not allowed when execution_mode=stateless"
        raise ValueError(msg)

    return normalized_mode, normalized_session


def extract_execution_session_handoff(result: ExecutionResult) -> dict[str, Any] | None:
    """Return the canonical continuity handoff payload from a Mente execution result."""
    payload = result.metadata.get("execution_session")
    if not isinstance(payload, dict):
        return None
    return dict(payload)


def build_cron_task(
    *,
    job: dict[str, Any],
    prompt: str,
    session_id: str,
    workspace: str | None = None,
) -> Task:
    """Create a normalized Mente task for a cron execution."""
    resolved_workspace = _resolve_workspace(workspace)
    schedule = job.get("schedule_display") or job.get("schedule") or "N/A"
    job_id = str(job.get("id") or "cron_job")
    job_name = str(job.get("name") or job_id)

    return Task(
        task_id=f"mente_cron_{job_id}_{uuid.uuid4().hex}",
        session_id=session_id,
        task_type="cron",
        objective=f"Execute scheduled job '{job_name}' and return a concise result.",
        user_request=prompt,
        workspace=resolved_workspace,
        constraints=[
            f"Cron job ID: {job_id}",
            f"Cron job name: {job_name}",
            f"Cron schedule: {schedule}",
        ],
        acceptance_criteria=[
            "Return a concise user-facing result for cron delivery.",
        ],
        execution_mode=ExecutionMode.STATELESS,
        metadata={
            "source": "cron",
            "tool_policy": _resolve_tool_policy(source="cron", task_type="cron"),
            "job": {
                "id": job.get("id"),
                "name": job.get("name"),
                "deliver": job.get("deliver"),
                "schedule": job.get("schedule"),
                "schedule_display": job.get("schedule_display"),
                "model": job.get("model"),
                "provider": job.get("provider"),
                "workdir": job.get("workdir"),
            },
        },
    )


def run_cron_task(
    *,
    job: dict[str, Any],
    prompt: str,
    session_id: str,
    workspace: str | None = None,
) -> ExecutionResult:
    """Execute a cron task through Mente."""
    task = build_cron_task(
        job=job,
        prompt=prompt,
        session_id=session_id,
        workspace=workspace,
    )
    return _run_task(task)


def build_gateway_task(
    *,
    message: str,
    context_prompt: str,
    history: list[dict[str, Any]],
    source: Any,
    session_id: str,
    session_key: str | None = None,
    channel_prompt: str | None = None,
    workspace: str | None = None,
    execution_mode: ExecutionMode | str | None = None,
    execution_session: ExecutionSession | dict[str, Any] | None = None,
    fallback_history_fact: str | None = None,
    replay_history_in_memory_facts: bool = True,
) -> Task:
    """Create a normalized Mente task for a gateway turn."""
    resolved_workspace = _resolve_workspace(workspace)
    memory_facts: list[str] = []
    normalized_execution_mode, normalized_execution_session = normalize_api_execution_continuity(
        execution_mode=execution_mode,
        execution_session=execution_session,
    )

    if context_prompt:
        memory_facts.append(f"Session context:\n{context_prompt}")
    if channel_prompt:
        memory_facts.append(f"Channel prompt:\n{channel_prompt}")
    history_fact = _build_conversation_history_fact(history)
    if history_fact and replay_history_in_memory_facts:
        memory_facts.append(history_fact)

    platform = source.platform.value if hasattr(source.platform, "value") else str(source.platform)
    metadata = {
        "source": "gateway",
        "tool_policy": _resolve_tool_policy(source="gateway", task_type="conversation"),
        "platform": platform,
        "session_key": session_key,
        "user_id": getattr(source, "user_id", None),
        "user_name": getattr(source, "user_name", None),
        "chat_id": getattr(source, "chat_id", None),
        "chat_name": getattr(source, "chat_name", None),
        "chat_type": getattr(source, "chat_type", None),
        "thread_id": getattr(source, "thread_id", None),
    }
    if fallback_history_fact:
        metadata["fallback_history_fact"] = fallback_history_fact

    return Task(
        task_id=f"mente_gateway_{uuid.uuid4().hex}",
        session_id=session_id,
        task_type="conversation",
        objective="Continue the active conversation and answer the latest user message.",
        user_request=message,
        workspace=resolved_workspace,
        memory_facts=memory_facts,
        acceptance_criteria=[
            "Respond directly to the latest user message.",
        ],
        execution_mode=normalized_execution_mode,
        execution_session=normalized_execution_session,
        metadata=metadata,
    )


def build_api_server_task(
    *,
    user_message: str,
    conversation_history: list[dict[str, Any]],
    session_id: str,
    api_mode: str,
    workspace: str | None = None,
    execution_mode: ExecutionMode | str | None = None,
    execution_session: ExecutionSession | dict[str, Any] | None = None,
    skill_refs: list[str] | tuple[str, ...] | None = None,
) -> Task:
    """Create a normalized Mente task for an API server request."""
    resolved_workspace = _resolve_workspace(workspace)
    memory_facts: list[str] = []
    normalized_skill_refs = _normalize_skill_refs(skill_refs)
    normalized_execution_mode, normalized_execution_session = normalize_api_execution_continuity(
        execution_mode=execution_mode,
        execution_session=execution_session,
    )

    history_fact = _build_conversation_history_fact(conversation_history)
    if history_fact:
        memory_facts.append(history_fact)

    return Task(
        task_id=f"mente_api_server_{uuid.uuid4().hex}",
        session_id=session_id,
        task_type="conversation",
        objective="Continue the active API conversation and answer the latest user message.",
        user_request=user_message,
        workspace=resolved_workspace,
        memory_facts=memory_facts,
        skill_refs=normalized_skill_refs,
        acceptance_criteria=[
            "Respond directly to the latest user message.",
        ],
        execution_mode=normalized_execution_mode,
        execution_session=normalized_execution_session,
        metadata={
            "source": "api_server",
            "api_mode": api_mode,
            "tool_policy": _resolve_tool_policy(source="api_server", task_type="conversation"),
            "workflow_contract": build_api_server_conversation_workflow_contract(
                skill_refs=normalized_skill_refs,
                execution_mode=normalized_execution_mode.value,
            ),
        },
    )


def build_tui_task(
    *,
    user_message: str,
    conversation_history: list[dict[str, Any]],
    session_id: str,
    workspace: str | None = None,
    execution_mode: ExecutionMode | str | None = None,
    execution_session: ExecutionSession | dict[str, Any] | None = None,
    fallback_history_fact: str | None = None,
    replay_history_in_memory_facts: bool = True,
) -> Task:
    """Create a normalized Mente task for one TUI conversation turn."""
    resolved_workspace = _resolve_workspace(workspace)
    memory_facts: list[str] = []
    normalized_execution_mode, normalized_execution_session = normalize_api_execution_continuity(
        execution_mode=execution_mode,
        execution_session=execution_session,
    )

    history_fact = _build_conversation_history_fact(conversation_history)
    if history_fact and replay_history_in_memory_facts:
        memory_facts.append(history_fact)

    metadata = {
        "source": "tui",
        "tool_policy": _resolve_tool_policy(source="tui", task_type="conversation"),
    }
    if fallback_history_fact:
        metadata["fallback_history_fact"] = fallback_history_fact

    return Task(
        task_id=f"mente_tui_{uuid.uuid4().hex}",
        session_id=session_id,
        task_type="conversation",
        objective="Continue the active TUI conversation and answer the latest user message.",
        user_request=user_message,
        workspace=resolved_workspace,
        memory_facts=memory_facts,
        acceptance_criteria=[
            "Respond directly to the latest user message.",
        ],
        execution_mode=normalized_execution_mode,
        execution_session=normalized_execution_session,
        metadata=metadata,
    )


def run_gateway_task(
    *,
    message: str,
    context_prompt: str,
    history: list[dict[str, Any]],
    source: Any,
    session_id: str,
    session_key: str | None = None,
    channel_prompt: str | None = None,
    workspace: str | None = None,
    execution_mode: ExecutionMode | str | None = None,
    execution_session: ExecutionSession | dict[str, Any] | None = None,
    fallback_history_fact: str | None = None,
    replay_history_in_memory_facts: bool = True,
    event_callback: ExecutionEventCallback | None = None,
) -> ExecutionResult:
    """Execute a gateway turn through Mente."""
    task = build_gateway_task(
        message=message,
        context_prompt=context_prompt,
        history=history,
        source=source,
        session_id=session_id,
        session_key=session_key,
        channel_prompt=channel_prompt,
        workspace=workspace,
        execution_mode=execution_mode,
        execution_session=execution_session,
        fallback_history_fact=fallback_history_fact,
        replay_history_in_memory_facts=replay_history_in_memory_facts,
    )
    repository = _build_task_repository()
    memory_repository = _build_memory_repository()
    try:
        result = _build_orchestrator(
            task.workspace or ".",
            repository,
            memory_repository,
            event_callback=event_callback,
        ).run(task)
        _persist_remember_intent_direct_write(
            task=task,
            result=result,
            repository=repository,
            memory_repository=memory_repository,
        )
        return result
    finally:
        for repo in (memory_repository, repository):
            close = getattr(repo, "close", None)
            if callable(close):
                close()


def run_api_server_task(
    *,
    user_message: str,
    conversation_history: list[dict[str, Any]],
    session_id: str,
    api_mode: str,
    workspace: str | None = None,
    execution_mode: ExecutionMode | str | None = None,
    execution_session: ExecutionSession | dict[str, Any] | None = None,
    skill_refs: list[str] | tuple[str, ...] | None = None,
) -> ExecutionResult:
    """Execute an API server turn through Mente."""
    task = build_api_server_task(
        user_message=user_message,
        conversation_history=conversation_history,
        session_id=session_id,
        api_mode=api_mode,
        workspace=workspace,
        execution_mode=execution_mode,
        execution_session=execution_session,
        skill_refs=skill_refs,
    )
    repository = _build_task_repository()
    memory_repository = _build_memory_repository()
    try:
        runtime_config = _resolve_runtime_config_for_workspace(task.workspace or ".")
        result = _build_orchestrator(
            task.workspace or ".",
            repository,
            memory_repository,
            executor=_APIServerIsolationExecutor(
                workspace=task.workspace or ".",
                runtime_config=runtime_config,
                memory_repository=memory_repository,
            ),
        ).run(task)
        result.metadata["remember_intent_direct_write"] = _persist_remember_intent_direct_write(
            task=task,
            result=result,
            repository=repository,
            memory_repository=memory_repository,
        )
        result.metadata["workflow_contract"] = dict(task.metadata.get("workflow_contract") or {})
        workflow_contract = result.metadata["workflow_contract"]
        memory_review_contract = workflow_contract.get("memory_review")
        if isinstance(memory_review_contract, dict) and bool(memory_review_contract.get("enabled")):
            result.metadata["memory_review"] = run_post_turn_memory_review(
                task_id=task.task_id,
                repository=repository,
                memory_repository=memory_repository,
            )
        skill_review_contract = workflow_contract.get("skill_review")
        if isinstance(skill_review_contract, dict) and bool(skill_review_contract.get("enabled")):
            result.metadata["skill_review"] = run_post_turn_skill_review(
                task_id=task.task_id,
                repository=repository,
            )
        session_synthesis_contract = workflow_contract.get("session_synthesis")
        if isinstance(session_synthesis_contract, dict) and bool(
            session_synthesis_contract.get("enabled")
        ):
            result.metadata["session_synthesis"] = run_post_turn_session_synthesis(
                task_id=task.task_id,
                repository=repository,
                memory_repository=memory_repository,
            )
        return result
    finally:
        for repo in (memory_repository, repository):
            close = getattr(repo, "close", None)
            if callable(close):
                close()


def run_tui_task(
    *,
    user_message: str,
    conversation_history: list[dict[str, Any]],
    session_id: str,
    workspace: str | None = None,
    execution_mode: ExecutionMode | str | None = None,
    execution_session: ExecutionSession | dict[str, Any] | None = None,
    fallback_history_fact: str | None = None,
    replay_history_in_memory_facts: bool = True,
    event_callback: ExecutionEventCallback | None = None,
    cancel_event: Any | None = None,
) -> ExecutionResult:
    """Execute one TUI turn through Mente."""
    task = build_tui_task(
        user_message=user_message,
        conversation_history=conversation_history,
        session_id=session_id,
        workspace=workspace,
        execution_mode=execution_mode,
        execution_session=execution_session,
        fallback_history_fact=fallback_history_fact,
        replay_history_in_memory_facts=replay_history_in_memory_facts,
    )
    repository = _build_task_repository()
    memory_repository = _build_memory_repository()
    try:
        result = _build_orchestrator(
            task.workspace or ".",
            repository,
            memory_repository,
            event_callback=event_callback,
            cancel_event=cancel_event,
        ).run(task)
        _persist_remember_intent_direct_write(
            task=task,
            result=result,
            repository=repository,
            memory_repository=memory_repository,
        )
        return result
    finally:
        for repo in (memory_repository, repository):
            close = getattr(repo, "close", None)
            if callable(close):
                close()


def _persist_remember_intent_direct_write(
    *,
    task: Task,
    result: ExecutionResult,
    repository: SQLiteTaskRepository,
    memory_repository: SQLiteMemoryRepository,
) -> dict[str, Any]:
    """Persist a narrow explicit remember-intent fact through the existing write seam."""

    outcome: dict[str, Any] = {
        "status": "noop",
        "reason": None,
        "candidate_count": 0,
        "persisted_count": 0,
        "memory_ids": [],
    }
    existing = task.metadata.get("remember_intent_direct_write")
    if isinstance(existing, dict) and existing.get("status") in {"skipped", "noop", "persisted"}:
        result.metadata["remember_intent_direct_write"] = dict(existing)
        return dict(existing)

    if result.status != "success":
        outcome["status"] = "skipped"
        outcome["reason"] = "upstream_not_success"
        return _persist_task_result_metadata(
            task=task,
            result=result,
            repository=repository,
            metadata_key="remember_intent_direct_write",
            metadata_value=outcome,
        )

    enabled, reason = _remember_intent_direct_write_enabled(task)
    if not enabled:
        outcome["status"] = "skipped"
        outcome["reason"] = reason or "disabled"
        return _persist_task_result_metadata(
            task=task,
            result=result,
            repository=repository,
            metadata_key="remember_intent_direct_write",
            metadata_value=outcome,
        )

    candidates = extract_explicit_remember_intent_facts(task.user_request)
    outcome["candidate_count"] = len(candidates)
    if not candidates:
        return _persist_task_result_metadata(
            task=task,
            result=result,
            repository=repository,
            metadata_key="remember_intent_direct_write",
            metadata_value=outcome,
        )

    record, write_reason = persist_explicit_memory_write(
        task,
        fact=candidates[0],
        memory_repository=memory_repository,
        tool_name="mente_remember_intent_direct_write",
        write_origin="explicit_remember_intent",
    )
    if record is None:
        outcome["status"] = "skipped"
        outcome["reason"] = write_reason or "write_failed"
        return _persist_task_result_metadata(
            task=task,
            result=result,
            repository=repository,
            metadata_key="remember_intent_direct_write",
            metadata_value=outcome,
        )

    if write_reason == "duplicate_existing":
        outcome["reason"] = "duplicate_existing"
        return _persist_task_result_metadata(
            task=task,
            result=result,
            repository=repository,
            metadata_key="remember_intent_direct_write",
            metadata_value=outcome,
        )

    outcome["status"] = "persisted"
    outcome["reason"] = write_reason
    outcome["persisted_count"] = 1
    outcome["memory_ids"] = [record.memory_id]
    return _persist_task_result_metadata(
        task=task,
        result=result,
        repository=repository,
        metadata_key="remember_intent_direct_write",
        metadata_value=outcome,
    )


def _remember_intent_direct_write_enabled(task: Task) -> tuple[bool, str | None]:
    """Return whether this task may use the direct-write remember-intent path."""

    if not is_remember_intent_direct_write_enabled():
        return False, "disabled"

    source = str(task.metadata.get("source") or "").strip()
    if not source:
        return False, "missing_source"
    if task.task_type != "conversation":
        return False, "unsupported_task_type"
    if source == "api_server":
        workflow_gate, workflow_reason = review_capability_gate(
            source=source,
            task_type=task.task_type,
            metadata=task.metadata,
            capability="remember_intent_direct_write",
        )
        if workflow_gate is not None:
            return workflow_gate, workflow_reason
    if source not in {"gateway", "api_server"}:
        return False, "unsupported_source"
    return True, None


def _persist_task_result_metadata(
    *,
    task: Task,
    result: ExecutionResult,
    repository: SQLiteTaskRepository,
    metadata_key: str,
    metadata_value: dict[str, Any],
) -> dict[str, Any]:
    """Persist one metadata payload onto both task and result surfaces."""

    payload = dict(metadata_value)
    task.metadata[metadata_key] = payload
    result.metadata[metadata_key] = payload
    repository.save(task)
    return payload


def run_post_turn_memory_review(
    *,
    task_id: str,
    repository: SQLiteTaskRepository | None = None,
    memory_repository: SQLiteMemoryRepository | None = None,
) -> dict[str, Any]:
    """Run the persisted post-turn memory review worker for one task."""
    owned_repository = repository is None
    owned_memory_repository = memory_repository is None
    repository = repository or _build_task_repository()
    memory_repository = memory_repository or _build_memory_repository()
    try:
        outcome = MemoryReviewWorker(
            task_repository=repository,
            memory_repository=memory_repository,
        ).review_task(task_id)
        return outcome.model_dump(mode="json")
    finally:
        for repo, owned in (
            (memory_repository, owned_memory_repository),
            (repository, owned_repository),
        ):
            if not owned:
                continue
            close = getattr(repo, "close", None)
            if callable(close):
                close()


def run_post_turn_skill_review(
    *,
    task_id: str,
    repository: SQLiteTaskRepository | None = None,
) -> dict[str, Any]:
    """Run the persisted post-turn skill review worker for one task."""
    owned_repository = repository is None
    repository = repository or _build_task_repository()
    try:
        outcome = SkillReviewWorker(task_repository=repository).review_task(task_id)
        return outcome.model_dump(mode="json")
    finally:
        if owned_repository:
            close = getattr(repository, "close", None)
            if callable(close):
                close()


def run_post_turn_session_synthesis(
    *,
    task_id: str,
    repository: SQLiteTaskRepository | None = None,
    memory_repository: SQLiteMemoryRepository | None = None,
) -> dict[str, Any]:
    """Run the persisted post-turn session synthesis worker for one task."""
    owned_repository = repository is None
    owned_memory_repository = memory_repository is None
    repository = repository or _build_task_repository()
    memory_repository = memory_repository or _build_memory_repository()
    try:
        outcome = SessionSynthesisWorker(
            task_repository=repository,
            memory_repository=memory_repository,
        ).review_task(task_id)
        return outcome.model_dump(mode="json")
    finally:
        for repo, owned in (
            (memory_repository, owned_memory_repository),
            (repository, owned_repository),
        ):
            if not owned:
                continue
            close = getattr(repo, "close", None)
            if callable(close):
                close()
