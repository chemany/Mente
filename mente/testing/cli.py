"""CLI entry point for replaying Mente fixtures."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from mente.context_builder.builder import ContextBuilder
from mente.executors.base import Executor
from mente.executors.codex import CodexExecutor
from mente.memory.promoter import MemoryPromoter
from mente.memory.repository import InMemoryMemoryRepository
from mente.orchestrator.service import Orchestrator
from mente.task_core.models import ExecutionRequest, ExecutionResult
from mente.task_core.repository import InMemoryTaskRepository
from mente.testing.replay import compare_memory_replay, load_replay_fixture, replay_task


class _MockReplayExecutor(Executor):
    """Small default executor for offline fixture replay."""

    def execute(self, request: ExecutionRequest) -> ExecutionResult:
        return ExecutionResult(status="success", summary=request.objective)


def build_replay_parser() -> argparse.ArgumentParser:
    """Build the replay CLI parser."""
    parser = argparse.ArgumentParser(prog="mente-replay")
    parser.add_argument("fixture_path")
    parser.add_argument("--executor", choices=("mock", "codex"), default="mock")
    parser.add_argument("--workspace", default=".")
    parser.add_argument("--compare-memory", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run a replay fixture through the Mente orchestrator."""
    args = build_replay_parser().parse_args(argv)
    executor: Executor
    if args.executor == "codex":
        executor = CodexExecutor()
    else:
        executor = _MockReplayExecutor()

    fixture = load_replay_fixture(args.fixture_path)
    if args.compare_memory:
        report = compare_memory_replay(
            fixture,
            executor_factory=CodexExecutor if args.executor == "codex" else _MockReplayExecutor,
            workspace=str(Path(args.workspace)),
        )
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0 if report["baseline"]["status"] == report["memory_enabled"]["status"] == "success" else 1

    memory_repository = InMemoryMemoryRepository()
    orchestrator = Orchestrator(
        repository=InMemoryTaskRepository(),
        context_builder=ContextBuilder(
            default_workspace=str(Path(args.workspace)),
            memory_repository=memory_repository,
        ),
        executor=executor,
        memory_repository=memory_repository,
        memory_promoter=MemoryPromoter(),
    )
    result = replay_task(fixture, orchestrator)
    print(result.summary)
    return 0 if result.status == "success" else 1
