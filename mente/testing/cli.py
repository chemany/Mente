"""CLI entry point for replaying Mente fixtures."""

from __future__ import annotations

import argparse
from pathlib import Path

from mente.context_builder.builder import ContextBuilder
from mente.executors.base import Executor
from mente.executors.codex import CodexExecutor
from mente.memory.repository import InMemoryMemoryRepository
from mente.orchestrator.service import Orchestrator
from mente.task_core.models import ExecutionRequest, ExecutionResult
from mente.task_core.repository import InMemoryTaskRepository
from mente.testing.replay import load_replay_fixture, replay_task


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
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run a replay fixture through the Mente orchestrator."""
    args = build_replay_parser().parse_args(argv)
    executor: Executor
    if args.executor == "codex":
        executor = CodexExecutor()
    else:
        executor = _MockReplayExecutor()

    orchestrator = Orchestrator(
        repository=InMemoryTaskRepository(),
        context_builder=ContextBuilder(
            default_workspace=str(Path(args.workspace)),
            memory_repository=InMemoryMemoryRepository(),
        ),
        executor=executor,
    )
    result = replay_task(load_replay_fixture(args.fixture_path), orchestrator)
    print(result.summary)
    return 0 if result.status == "success" else 1
