"""Benchmark suite models and deterministic replay scoring helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from mente.executors.base import Executor
from mente.memory.policy import MemoryPolicy
from mente.task_core.models import ExecutionRequest, ExecutionResult
from mente.testing.replay import compare_memory_replay, load_replay_fixture


class BenchmarkExpectation(BaseModel):
    selected_memory_ids: list[str] | None = None
    memory_fact_count: int | None = None
    policy_id: str | None = None
    promoted_memory_ids: list[str] | None = None
    max_prompt_char_count: int | None = None
    max_prompt_budget_char_count: int | None = None


class BenchmarkCase(BaseModel):
    case_id: str
    fixture_path: str
    expectations: dict[str, BenchmarkExpectation]


class BenchmarkSuite(BaseModel):
    suite_id: str
    notes: str = ""
    policy_variants: dict[str, MemoryPolicy]
    cases: list[BenchmarkCase]


def load_benchmark_suite(path: str | Path) -> BenchmarkSuite:
    """Load a benchmark suite manifest from disk."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return BenchmarkSuite.model_validate(payload)


class _MockReplayExecutor(Executor):
    """Default offline executor for benchmark replay runs."""

    def execute(self, request: ExecutionRequest) -> ExecutionResult:
        return ExecutionResult(status="success", summary=request.objective)


def _build_check(passed: bool, expected: Any, actual: Any) -> dict[str, Any]:
    return {
        "passed": passed,
        "expected": expected,
        "actual": actual,
    }


def _score_expectation(
    result: dict[str, Any],
    expectation: BenchmarkExpectation,
) -> dict[str, Any]:
    checks: dict[str, dict[str, Any]] = {}

    if expectation.selected_memory_ids is not None:
        actual = result.get("selected_memory_ids", [])
        checks["selected_memory_ids"] = _build_check(
            actual == expectation.selected_memory_ids,
            expectation.selected_memory_ids,
            actual,
        )
    if expectation.memory_fact_count is not None:
        actual = result.get("memory_fact_count")
        checks["memory_fact_count"] = _build_check(
            actual == expectation.memory_fact_count,
            expectation.memory_fact_count,
            actual,
        )
    if expectation.policy_id is not None:
        actual = result.get("policy_id")
        checks["policy_id"] = _build_check(
            actual == expectation.policy_id,
            expectation.policy_id,
            actual,
        )
    if expectation.promoted_memory_ids is not None:
        actual = result.get("promoted_memory_ids", [])
        checks["promoted_memory_ids"] = _build_check(
            actual == expectation.promoted_memory_ids,
            expectation.promoted_memory_ids,
            actual,
        )
    if expectation.max_prompt_char_count is not None:
        actual = result.get("prompt_char_count")
        checks["max_prompt_char_count"] = _build_check(
            isinstance(actual, int) and actual <= expectation.max_prompt_char_count,
            expectation.max_prompt_char_count,
            actual,
        )
    if expectation.max_prompt_budget_char_count is not None:
        actual = result.get("prompt_budget_char_count")
        checks["max_prompt_budget_char_count"] = _build_check(
            isinstance(actual, int) and actual <= expectation.max_prompt_budget_char_count,
            expectation.max_prompt_budget_char_count,
            actual,
        )

    passed_checks = sum(1 for item in checks.values() if item["passed"])
    total_checks = len(checks)
    score = passed_checks / total_checks if total_checks else 1.0
    return {
        "status": "pass" if total_checks == passed_checks else "fail",
        "score": score,
        "checks": checks,
    }


def evaluate_benchmark_case(
    case: BenchmarkCase,
    suite: BenchmarkSuite,
    *,
    executor_factory=None,
    workspace: str = ".",
) -> list[dict[str, Any]]:
    """Evaluate one case against each declared policy expectation."""
    fixture = load_replay_fixture(Path(workspace) / case.fixture_path)
    executor_factory = executor_factory or _MockReplayExecutor
    runs: list[dict[str, Any]] = []

    for policy_variant, expectation in case.expectations.items():
        comparison = compare_memory_replay(
            fixture,
            executor_factory=executor_factory,
            workspace=workspace,
            policy_override=suite.policy_variants[policy_variant],
        )
        result = comparison["memory_enabled"]
        scoring = _score_expectation(result, expectation)
        runs.append(
            {
                "case_id": case.case_id,
                "policy_variant": policy_variant,
                "status": scoring["status"],
                "score": scoring["score"],
                "checks": scoring["checks"],
                "result": result,
            }
        )

    return runs


def run_benchmark_suite(
    suite: BenchmarkSuite,
    executor_factory=None,
    workspace: str = ".",
) -> dict[str, Any]:
    """Run every benchmark case against its declared policy variants."""
    runs: list[dict[str, Any]] = []
    for case in suite.cases:
        runs.extend(
            evaluate_benchmark_case(
                case,
                suite,
                executor_factory=executor_factory,
                workspace=workspace,
            )
        )

    pass_count = sum(1 for run in runs if run["status"] == "pass")
    fail_count = len(runs) - pass_count
    average_score = sum(run["score"] for run in runs) / len(runs) if runs else 0.0
    return {
        "suite_id": suite.suite_id,
        "summary": {
            "case_count": len(suite.cases),
            "policy_run_count": len(runs),
            "pass_count": pass_count,
            "fail_count": fail_count,
            "average_score": average_score,
        },
        "runs": runs,
    }
