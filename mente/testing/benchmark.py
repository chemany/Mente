"""Benchmark suite models and loader helpers for offline replay evaluation."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel

from mente.memory.policy import MemoryPolicy


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
