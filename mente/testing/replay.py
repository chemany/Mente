"""Replay helpers for normalized Mente task fixtures."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mente.context_builder.builder import ContextBuilder
from mente.executors.base import Executor
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
    return Task.model_validate(fixture["task"])


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


def _run_replay_mode(
    fixture: dict[str, Any],
    *,
    executor_factory,
    workspace: str,
    memory_enabled: bool,
) -> tuple[ExecutionResult, Any]:
    task = build_task_from_fixture(fixture).model_copy(deep=True)
    if task.workspace is None:
        task.workspace = workspace

    memory_repository = _build_seeded_memory_repository(fixture, enabled=memory_enabled)
    executor = _CaptureExecutor(executor_factory())
    orchestrator = Orchestrator(
        repository=InMemoryTaskRepository(),
        context_builder=ContextBuilder(
            default_workspace=workspace,
            memory_repository=memory_repository,
        ),
        executor=executor,
        memory_repository=memory_repository,
        memory_promoter=MemoryPromoter(),
    )
    result = orchestrator.run(task)
    return result, executor.last_request


def compare_memory_replay(
    fixture: dict[str, Any],
    executor_factory,
    workspace: str = ".",
) -> dict[str, Any]:
    """Compare a replay run with memory disabled versus enabled."""
    baseline_result, baseline_request = _run_replay_mode(
        fixture,
        executor_factory=executor_factory,
        workspace=workspace,
        memory_enabled=False,
    )
    memory_result, memory_request = _run_replay_mode(
        fixture,
        executor_factory=executor_factory,
        workspace=workspace,
        memory_enabled=True,
    )

    memory_context = memory_result.metadata.get("memory_context", {})
    memory_promotion = memory_result.metadata.get("memory_promotion", {})
    selected = memory_context.get("selected", [])

    return {
        "baseline": {
            "memory_fact_count": len(baseline_request.memory_facts),
            "memory_facts": list(baseline_request.memory_facts),
            "status": baseline_result.status,
        },
        "memory_enabled": {
            "memory_fact_count": len(memory_request.memory_facts),
            "memory_facts": list(memory_request.memory_facts),
            "selected_memory_ids": [item["memory_id"] for item in selected],
            "promoted_memory_ids": list(memory_promotion.get("promoted_memory_ids", [])),
            "status": memory_result.status,
        },
    }
