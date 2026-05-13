"""Replay helpers for normalized Mente task fixtures."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mente.context_builder.builder import ContextBuilder
from mente.executors import resolve_tool_exposure_policy
from mente.feature_flags import build_api_server_conversation_workflow_contract, build_conversation_workflow_contract
from mente.executors.base import Executor
from mente.executors.prompting import build_prompt_metrics
from mente.memory.policy import MemoryPolicy, MemoryPolicyResolver
from mente.memory.models import MemoryRecord
from mente.memory.promoter import MemoryPromoter
from mente.memory.repository import InMemoryMemoryRepository
from mente.orchestrator.service import Orchestrator
from mente.task_core.models import ExecutionResult, Task
from mente.task_core.repository import InMemoryTaskRepository


def load_replay_fixture(path: str | Path) -> dict[str, Any]:
    """Load a replay fixture from disk."""
    return json.loads(Path(path).read_text(encoding="utf-8"))


def build_task_from_fixture(fixture: dict[str, Any]) -> Task:
    """Construct a normalized task from a replay fixture."""
    task = Task.model_validate(fixture["task"])
    if task.task_type != "conversation":
        return task

    metadata = dict(task.metadata)
    source = str(metadata.get("source") or "").strip()
    if not source:
        task.metadata = metadata
        return task

    lane = str(metadata.get("lane") or "").strip().lower() or "director"
    metadata.setdefault("lane", lane)
    if "workflow_contract" not in metadata:
        if source == "api_server":
            metadata["workflow_contract"] = build_api_server_conversation_workflow_contract()
        else:
            metadata["workflow_contract"] = build_conversation_workflow_contract(
                source=source,
                lane=lane,
            )
    task.metadata = metadata
    return task


def replay_task(fixture: dict[str, Any], orchestrator: Orchestrator) -> ExecutionResult:
    """Replay a normalized task fixture through the orchestrator."""
    return orchestrator.run(build_task_from_fixture(fixture))


class _CaptureExecutor(Executor):
    """Record the last execution request while delegating to the real executor."""

    def __init__(self, delegate: Executor) -> None:
        self.delegate = delegate
        self.last_request = None

    def execute(self, request) -> ExecutionResult:
        self.last_request = request
        return self.delegate.execute(request)


def _build_seeded_memory_repository(fixture: dict[str, Any], *, enabled: bool) -> InMemoryMemoryRepository:
    repository = InMemoryMemoryRepository()
    if not enabled:
        return repository

    for payload in fixture.get("seed_memories", []):
        repository.save(MemoryRecord.model_validate(payload))
    return repository


def _build_memory_policy_resolver(
    task: Task,
    policy_override: MemoryPolicy | None,
) -> MemoryPolicyResolver:
    resolver = MemoryPolicyResolver.default()
    if policy_override is None:
        return resolver

    candidates = []
    source = str(task.metadata.get("source") or "").strip()
    if source:
        candidates.append(f"{source}:{task.task_type}")
    candidates.append(task.task_type)
    candidates.append(resolver.default_policy_id)

    profiles = dict(resolver.profiles)
    for policy_key in candidates:
        if policy_key in profiles:
            profiles[policy_key] = policy_override
            break
    else:
        profiles[resolver.default_policy_id] = policy_override
    return MemoryPolicyResolver(
        profiles=profiles,
        default_policy_id=resolver.default_policy_id,
    )


def _run_replay_mode(
    fixture: dict[str, Any],
    *,
    executor_factory,
    workspace: str,
    memory_enabled: bool,
    policy_override: MemoryPolicy | None = None,
) -> tuple[ExecutionResult, Any, InMemoryMemoryRepository]:
    task = build_task_from_fixture(fixture).model_copy(deep=True)
    if task.workspace is None:
        task.workspace = workspace
    if "tool_policy" not in task.metadata:
        source = str(task.metadata.get("source") or "").strip()
        if source:
            task.metadata["tool_policy"] = resolve_tool_exposure_policy(
                source=source,
                task_type=task.task_type,
            ).as_metadata()

    memory_repository = _build_seeded_memory_repository(fixture, enabled=memory_enabled)
    executor = _CaptureExecutor(executor_factory())
    memory_policy_resolver = _build_memory_policy_resolver(task, policy_override)
    orchestrator = Orchestrator(
        repository=InMemoryTaskRepository(),
        context_builder=ContextBuilder(
            default_workspace=workspace,
            memory_repository=memory_repository,
            memory_policy_resolver=memory_policy_resolver,
        ),
        executor=executor,
        memory_repository=memory_repository,
        memory_promoter=MemoryPromoter(memory_policy_resolver=memory_policy_resolver),
    )
    result = orchestrator.run(task)
    return result, executor.last_request, memory_repository


def compare_memory_replay(
    fixture: dict[str, Any],
    executor_factory,
    workspace: str = ".",
    policy_override: MemoryPolicy | None = None,
) -> dict[str, Any]:
    """Compare a replay run with memory disabled versus enabled."""
    baseline_result, baseline_request, baseline_repository = _run_replay_mode(
        fixture,
        executor_factory=executor_factory,
        workspace=workspace,
        memory_enabled=False,
        policy_override=policy_override,
    )
    memory_result, memory_request, memory_repository = _run_replay_mode(
        fixture,
        executor_factory=executor_factory,
        workspace=workspace,
        memory_enabled=True,
        policy_override=policy_override,
    )

    memory_context = memory_result.metadata.get("memory_context", {})
    memory_promotion = memory_result.metadata.get("memory_promotion", {})
    memory_policy = memory_result.metadata.get("memory_policy", {})
    baseline_context = baseline_result.metadata.get("memory_context", {})
    baseline_promotion = baseline_result.metadata.get("memory_promotion", {})
    baseline_policy = baseline_result.metadata.get("memory_policy", {})
    selected = memory_context.get("selected", [])
    baseline_selected = baseline_context.get("selected", [])
    baseline_superseded_ids = [
        record.memory_id
        for record in baseline_repository.list_recent(limit=200, include_inactive=True)
        if not record.active
    ]
    memory_superseded_ids = [
        record.memory_id
        for record in memory_repository.list_recent(limit=200, include_inactive=True)
        if not record.active
    ]

    return {
        "baseline": {
            **build_prompt_metrics(baseline_request),
            "memory_facts": list(baseline_request.memory_facts),
            "policy_id": baseline_policy.get("policy_id"),
            "prompt_budget_char_count": baseline_context.get("prompt_budget_char_count", 0),
            "selected_memory_ids": [item["memory_id"] for item in baseline_selected],
            "promoted_memory_ids": list(baseline_promotion.get("promoted_memory_ids", [])),
            "superseded_memory_ids": baseline_superseded_ids,
            "status": baseline_result.status,
        },
        "memory_enabled": {
            **build_prompt_metrics(memory_request),
            "memory_facts": list(memory_request.memory_facts),
            "policy_id": memory_policy.get("policy_id"),
            "prompt_budget_char_count": memory_context.get("prompt_budget_char_count", 0),
            "selected_memory_ids": [item["memory_id"] for item in selected],
            "promoted_memory_ids": list(memory_promotion.get("promoted_memory_ids", [])),
            "superseded_memory_ids": memory_superseded_ids,
            "status": memory_result.status,
        },
    }
