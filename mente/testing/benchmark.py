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


def _sorted_benchmark_runs(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        [dict(run) for run in runs],
        key=lambda item: (item["case_id"], item["policy_variant"]),
    )


def normalize_benchmark_report(report: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(report)
    normalized["runs"] = _sorted_benchmark_runs(report.get("runs", []))
    return normalized


def write_benchmark_baseline(report: dict[str, Any], path: str | Path) -> None:
    Path(path).write_text(
        json.dumps(normalize_benchmark_report(report), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def load_benchmark_baseline(path: str | Path) -> dict[str, Any]:
    return normalize_benchmark_report(
        json.loads(Path(path).read_text(encoding="utf-8"))
    )


def _index_benchmark_runs(
    report: dict[str, Any],
) -> dict[tuple[str, str], dict[str, Any]]:
    return {
        (run["case_id"], run["policy_variant"]): run
        for run in report.get("runs", [])
    }


def compare_benchmark_report_to_baseline(
    current: dict[str, Any],
    baseline: dict[str, Any],
) -> dict[str, Any]:
    normalized_current = normalize_benchmark_report(current)
    normalized_baseline = normalize_benchmark_report(baseline)
    current_runs = _index_benchmark_runs(normalized_current)
    baseline_runs = _index_benchmark_runs(normalized_baseline)
    run_keys = sorted(set(baseline_runs) | set(current_runs))
    comparison_runs: list[dict[str, Any]] = []
    regression_count = 0
    improvement_count = 0
    missing_run_count = 0
    new_run_count = 0

    for case_id, policy_variant in run_keys:
        baseline_run = baseline_runs.get((case_id, policy_variant))
        current_run = current_runs.get((case_id, policy_variant))
        reasons: list[str] = []

        if baseline_run and not current_run:
            reasons.append("missing_run")
            missing_run_count += 1
        elif current_run and not baseline_run:
            reasons.append("new_run")
            new_run_count += 1
        else:
            assert baseline_run is not None
            assert current_run is not None
            if baseline_run["status"] == "pass" and current_run["status"] == "fail":
                reasons.append("status_degraded")
            elif baseline_run["status"] == "fail" and current_run["status"] == "pass":
                reasons.append("status_improved")

            if current_run["score"] < baseline_run["score"]:
                reasons.append("score_decreased")
            elif current_run["score"] > baseline_run["score"]:
                reasons.append("score_increased")

        is_regression = any(reason in {"missing_run", "status_degraded", "score_decreased"} for reason in reasons)
        is_improvement = any(
            reason in {"status_improved", "score_increased"} for reason in reasons
        )
        if is_regression:
            regression_count += 1
        if is_improvement:
            improvement_count += 1

        comparison_runs.append(
            {
                "case_id": case_id,
                "policy_variant": policy_variant,
                "baseline_status": baseline_run["status"] if baseline_run else None,
                "current_status": current_run["status"] if current_run else None,
                "baseline_score": baseline_run["score"] if baseline_run else None,
                "current_score": current_run["score"] if current_run else None,
                "is_regression": is_regression,
                "is_improvement": is_improvement,
                "reasons": reasons,
            }
        )

    summary_reasons: list[str] = []
    baseline_summary = normalized_baseline.get("summary", {})
    current_summary = normalized_current.get("summary", {})
    if current_summary.get("fail_count", 0) > baseline_summary.get("fail_count", 0):
        summary_reasons.append("fail_count_increased")
        regression_count += 1
    elif current_summary.get("fail_count", 0) < baseline_summary.get("fail_count", 0):
        summary_reasons.append("fail_count_decreased")
        improvement_count += 1

    if current_summary.get("average_score", 0.0) < baseline_summary.get("average_score", 0.0):
        summary_reasons.append("average_score_decreased")
        regression_count += 1
    elif current_summary.get("average_score", 0.0) > baseline_summary.get("average_score", 0.0):
        summary_reasons.append("average_score_increased")
        improvement_count += 1

    status = "unchanged"
    if regression_count > 0:
        status = "regression"
    elif improvement_count > 0:
        status = "improved"

    return {
        "suite_id": normalized_current.get(
            "suite_id", normalized_baseline.get("suite_id")
        ),
        "summary": {
            "baseline_policy_run_count": baseline_summary.get("policy_run_count", 0),
            "current_policy_run_count": current_summary.get("policy_run_count", 0),
            "regression_count": regression_count,
            "improvement_count": improvement_count,
            "missing_run_count": missing_run_count,
            "new_run_count": new_run_count,
            "status": status,
            "reasons": summary_reasons,
        },
        "runs": comparison_runs,
    }
