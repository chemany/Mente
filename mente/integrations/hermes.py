"""Thin Hermes-to-Mente task bridge helpers."""

from __future__ import annotations

import json
import os
import uuid
from typing import Any

from mente.context_builder.builder import ContextBuilder
from mente.executors.base import Executor
from mente.executors.codex import CodexExecutor
from mente.memory.promoter import MemoryPromoter
from mente.memory.repository import SQLiteMemoryRepository
from mente.orchestrator.service import Orchestrator
from mente.task_core.models import ExecutionRequest, ExecutionResult, Task
from mente.task_core.repository import SQLiteTaskRepository


def _resolve_workspace(workspace: str | None) -> str:
    """Resolve the workspace used for a bridged task."""
    return workspace or os.getenv("TERMINAL_CWD") or os.getcwd()


def _build_task_repository() -> SQLiteTaskRepository:
    """Create the default persistent task repository."""
    return SQLiteTaskRepository()


def _build_memory_repository() -> SQLiteMemoryRepository:
    """Create the default persistent memory repository."""
    return SQLiteMemoryRepository()


def _build_orchestrator(
    workspace: str,
    repository,
    memory_repository: SQLiteMemoryRepository | None = None,
    executor: Executor | None = None,
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
        executor=executor or CodexExecutor(),
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


class _APIServerIsolationExecutor(Executor):
    """Wrap Codex execution with empty-session isolation for API server turns."""

    def __init__(self, inner: Executor | None = None) -> None:
        self._inner = inner or CodexExecutor()

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
        metadata={
            "source": "cron",
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
) -> Task:
    """Create a normalized Mente task for a gateway turn."""
    resolved_workspace = _resolve_workspace(workspace)
    memory_facts: list[str] = []

    if context_prompt:
        memory_facts.append(f"Session context:\n{context_prompt}")
    if channel_prompt:
        memory_facts.append(f"Channel prompt:\n{channel_prompt}")
    history_fact = _build_conversation_history_fact(history)
    if history_fact:
        memory_facts.append(history_fact)

    platform = source.platform.value if hasattr(source.platform, "value") else str(source.platform)
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
        metadata={
            "source": "gateway",
            "platform": platform,
            "session_key": session_key,
            "user_id": getattr(source, "user_id", None),
            "user_name": getattr(source, "user_name", None),
            "chat_id": getattr(source, "chat_id", None),
            "chat_name": getattr(source, "chat_name", None),
            "chat_type": getattr(source, "chat_type", None),
            "thread_id": getattr(source, "thread_id", None),
        },
    )


def build_api_server_task(
    *,
    user_message: str,
    conversation_history: list[dict[str, Any]],
    session_id: str,
    api_mode: str,
    workspace: str | None = None,
) -> Task:
    """Create a normalized Mente task for an API server request."""
    resolved_workspace = _resolve_workspace(workspace)
    memory_facts: list[str] = []

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
        acceptance_criteria=[
            "Respond directly to the latest user message.",
        ],
        metadata={
            "source": "api_server",
            "api_mode": api_mode,
        },
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
    )
    return _run_task(task)


def run_api_server_task(
    *,
    user_message: str,
    conversation_history: list[dict[str, Any]],
    session_id: str,
    api_mode: str,
    workspace: str | None = None,
) -> ExecutionResult:
    """Execute an API server turn through Mente."""
    task = build_api_server_task(
        user_message=user_message,
        conversation_history=conversation_history,
        session_id=session_id,
        api_mode=api_mode,
        workspace=workspace,
    )
    repository = _build_task_repository()
    memory_repository = _build_memory_repository()
    try:
        return _build_orchestrator(
            task.workspace or ".",
            repository,
            memory_repository,
            executor=_APIServerIsolationExecutor(),
        ).run(task)
    finally:
        for repo in (memory_repository, repository):
            close = getattr(repo, "close", None)
            if callable(close):
                close()
