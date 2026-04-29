"""Live evaluation suite models and manifest loading helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel


class LiveEvalTurn(BaseModel):
    user_message: str


class LiveEvalAcceptance(BaseModel):
    min_task_count: int | None = None
    expected_task_source: str | None = None
    expected_task_type: str | None = None
    min_promoted_memory_count: int | None = None
    selected_memory_ids_present: list[str] | None = None
    policy_id: str | None = None
    max_prompt_budget_char_count: int | None = None


class LiveEvalCase(BaseModel):
    case_id: str
    session_id_seed: str
    turns: list[LiveEvalTurn]
    acceptance: LiveEvalAcceptance


class LiveEvalSuite(BaseModel):
    suite_id: str
    notes: str = ""
    cases: list[LiveEvalCase]


def load_live_eval_suite(path: str | Path) -> LiveEvalSuite:
    """Load a live evaluation suite manifest from disk."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return LiveEvalSuite.model_validate(payload)


def _build_check(
    name: str,
    passed: bool,
    expected: Any,
    actual: Any,
) -> dict[str, Any]:
    return {
        "passed": passed,
        "expected": expected,
        "actual": actual,
        "reason": "" if passed else f"{name} check failed",
    }


def evaluate_live_eval_case(
    case: LiveEvalCase,
    task_page: dict[str, Any],
    memory_page: dict[str, Any],
    execution_trace: dict[str, Any],
) -> dict[str, Any]:
    """Evaluate one live-eval case against captured debug data."""
    acceptance = case.acceptance
    tasks = list(task_page.get("tasks", []))
    memories = list(memory_page.get("memories", []))
    selected_memory_ids = list(execution_trace.get("selected_memory_ids", []))
    promoted_memory_ids = list(execution_trace.get("promoted_memory_ids", []))
    task_sources = [task.get("metadata", {}).get("source") for task in tasks]
    task_types = [task.get("task_type") for task in tasks]
    checks: dict[str, dict[str, Any]] = {}

    if acceptance.min_task_count is not None:
        checks["min_task_count"] = _build_check(
            "min_task_count",
            len(tasks) >= acceptance.min_task_count,
            acceptance.min_task_count,
            len(tasks),
        )
    if acceptance.expected_task_source is not None:
        checks["expected_task_source"] = _build_check(
            "expected_task_source",
            bool(tasks) and all(
                source == acceptance.expected_task_source for source in task_sources
            ),
            acceptance.expected_task_source,
            task_sources,
        )
    if acceptance.expected_task_type is not None:
        checks["expected_task_type"] = _build_check(
            "expected_task_type",
            bool(tasks) and all(
                task_type == acceptance.expected_task_type for task_type in task_types
            ),
            acceptance.expected_task_type,
            task_types,
        )
    if acceptance.min_promoted_memory_count is not None:
        checks["min_promoted_memory_count"] = _build_check(
            "min_promoted_memory_count",
            len(promoted_memory_ids) >= acceptance.min_promoted_memory_count,
            acceptance.min_promoted_memory_count,
            len(promoted_memory_ids),
        )
    if acceptance.selected_memory_ids_present is not None:
        expected_ids = list(acceptance.selected_memory_ids_present)
        checks["selected_memory_ids_present"] = _build_check(
            "selected_memory_ids_present",
            all(memory_id in selected_memory_ids for memory_id in expected_ids),
            expected_ids,
            selected_memory_ids,
        )
    if acceptance.policy_id is not None:
        checks["policy_id"] = _build_check(
            "policy_id",
            execution_trace.get("policy_id") == acceptance.policy_id,
            acceptance.policy_id,
            execution_trace.get("policy_id"),
        )
    if acceptance.max_prompt_budget_char_count is not None:
        prompt_budget = execution_trace.get("prompt_budget_char_count")
        checks["max_prompt_budget_char_count"] = _build_check(
            "max_prompt_budget_char_count",
            isinstance(prompt_budget, int)
            and prompt_budget <= acceptance.max_prompt_budget_char_count,
            acceptance.max_prompt_budget_char_count,
            prompt_budget,
        )

    total_checks = len(checks)
    passed_checks = sum(1 for check in checks.values() if check["passed"])
    return {
        "case_id": case.case_id,
        "status": "pass" if passed_checks == total_checks else "fail",
        "score": passed_checks / total_checks if total_checks else 1.0,
        "checks": checks,
        "task_count": len(tasks),
        "memory_count": len(memories),
        "selected_memory_ids": selected_memory_ids,
        "promoted_memory_ids": promoted_memory_ids,
    }
