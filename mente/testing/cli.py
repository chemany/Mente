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
from mente.testing.benchmark import (
    compare_benchmark_report_to_baseline,
    load_benchmark_baseline,
    load_benchmark_suite,
    normalize_benchmark_report,
    run_benchmark_suite,
    write_benchmark_baseline,
)
from mente.testing.live_eval import load_live_eval_suite, run_live_eval_suite
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
    parser.add_argument("--show-prompt-metrics", action="store_true")
    parser.add_argument("--benchmark-suite")
    parser.add_argument("--baseline")
    parser.add_argument("--write-baseline")
    parser.add_argument("--output-report")
    parser.add_argument("--fail-on-regression", action="store_true")
    parser.add_argument("--live-eval-suite")
    parser.add_argument("--api-base-url")
    parser.add_argument("--api-key")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run a replay fixture through the Mente orchestrator."""
    args = build_replay_parser().parse_args(argv)
    executor_factory = CodexExecutor if args.executor == "codex" else _MockReplayExecutor

    if args.live_eval_suite:
        report = run_live_eval_suite(
            load_live_eval_suite(args.live_eval_suite),
            api_base_url=str(args.api_base_url or ""),
            api_key=args.api_key,
        )
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0 if report["summary"]["fail_count"] == 0 else 1

    if args.benchmark_suite:
        suite = load_benchmark_suite(args.benchmark_suite)
        report = run_benchmark_suite(
            suite,
            executor_factory=executor_factory,
            workspace=str(Path(args.workspace)),
        )
        if args.write_baseline:
            write_benchmark_baseline(report, args.write_baseline)

        payload = normalize_benchmark_report(report)
        if args.baseline:
            baseline = load_benchmark_baseline(args.baseline)
            payload = compare_benchmark_report_to_baseline(report, baseline)

        if args.output_report:
            Path(args.output_report).write_text(
                json.dumps(payload, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )

        print(json.dumps(payload, indent=2, sort_keys=True))
        if args.fail_on_regression and args.baseline:
            return 1 if payload["summary"]["regression_count"] > 0 else 0
        if args.write_baseline and not args.baseline:
            return 0
        return 0 if report["summary"]["fail_count"] == 0 else 1

    executor: Executor = executor_factory()

    fixture = load_replay_fixture(args.fixture_path)
    if args.compare_memory:
        report = compare_memory_replay(
            fixture,
            executor_factory=executor_factory,
            workspace=str(Path(args.workspace)),
        )
        if args.show_prompt_metrics:
            print(json.dumps(report, indent=2, sort_keys=True))
        else:
            concise_report = {
                mode: {
                    "status": payload["status"],
                    "memory_fact_count": payload["memory_fact_count"],
                    "policy_id": payload["policy_id"],
                    "selected_memory_ids": payload["selected_memory_ids"],
                    "promoted_memory_ids": payload["promoted_memory_ids"],
                }
                for mode, payload in report.items()
            }
            print(json.dumps(concise_report, indent=2, sort_keys=True))
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
