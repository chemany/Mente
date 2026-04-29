"""Live evaluation suite models and manifest loading helpers."""

from __future__ import annotations

import json
from pathlib import Path

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
