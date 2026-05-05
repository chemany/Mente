"""Live evaluation suite models and manifest loading helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import requests
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
    superseded_memory_ids = list(execution_trace.get("superseded_memory_ids", []))
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
        "superseded_memory_ids": superseded_memory_ids,
    }


def _build_auth_headers(api_key: str | None) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


def _request_json(
    method: str,
    url: str,
    *,
    api_key: str | None,
    payload: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    response = requests.request(
        method,
        url,
        headers=_build_auth_headers(api_key),
        json=payload,
        params=params,
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def _extract_execution_trace(task_page: dict[str, Any], memory_page: dict[str, Any]) -> dict[str, Any]:
    tasks = list(task_page.get("tasks", []))
    latest_task = tasks[0] if tasks else {}
    metadata = latest_task.get("metadata", {})
    memory_context = metadata.get("memory_context", {})
    memory_policy = metadata.get("memory_policy", {})
    memory_promotion = metadata.get("memory_promotion", {})
    selected = list(memory_context.get("selected", []))

    return {
        "policy_id": memory_policy.get("policy_id"),
        "prompt_budget_char_count": memory_context.get("prompt_budget_char_count"),
        "selected_memory_ids": [
            item["memory_id"] for item in selected if isinstance(item, dict) and "memory_id" in item
        ],
        "promoted_memory_ids": list(memory_promotion.get("promoted_memory_ids", [])),
        "superseded_memory_ids": [
            memory.get("memory_id")
            for memory in memory_page.get("memories", [])
            if isinstance(memory, dict) and memory.get("active") is False and memory.get("memory_id")
        ],
    }


def run_live_eval_suite(
    suite: LiveEvalSuite,
    *,
    api_base_url: str,
    api_key: str | None = None,
) -> dict[str, Any]:
    """Run a live evaluation suite against the API server debug surfaces."""
    base_url = api_base_url.rstrip("/")
    case_reports: list[dict[str, Any]] = []

    for case in suite.cases:
        for turn in case.turns:
            _request_json(
                "POST",
                f"{base_url}/v1/responses",
                api_key=api_key,
                payload={
                    "input": turn.user_message,
                    "conversation": case.session_id_seed,
                    "store": True,
                },
            )

        task_page = _request_json(
            "GET",
            f"{base_url}/api/debug/tasks",
            api_key=api_key,
            params={
                "scope": "session",
                "session_id": case.session_id_seed,
                "source": "gateway",
                "task_type": "conversation",
                "limit": 20,
            },
        )
        memory_page = _request_json(
            "GET",
            f"{base_url}/api/debug/memories",
            api_key=api_key,
            params={
                "scope": "session",
                "session_id": case.session_id_seed,
                "source": "gateway",
                "task_type": "conversation",
                "limit": 20,
            },
        )
        report = evaluate_live_eval_case(
            case,
            task_page,
            memory_page,
            _extract_execution_trace(task_page, memory_page),
        )
        case_reports.append(report)

    pass_count = sum(1 for report in case_reports if report["status"] == "pass")
    fail_count = len(case_reports) - pass_count
    return {
        "suite_id": suite.suite_id,
        "summary": {
            "case_count": len(case_reports),
            "pass_count": pass_count,
            "fail_count": fail_count,
        },
        "cases": case_reports,
    }
