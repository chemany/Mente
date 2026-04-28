"""Replay helpers for normalized Mente task fixtures."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mente.orchestrator.service import Orchestrator
from mente.task_core.models import ExecutionResult, Task


def load_replay_fixture(path: str | Path) -> dict[str, Any]:
    """Load a replay fixture from disk."""
    return json.loads(Path(path).read_text(encoding="utf-8"))


def build_task_from_fixture(fixture: dict[str, Any]) -> Task:
    """Construct a normalized task from a replay fixture."""
    return Task.model_validate(fixture["task"])


def replay_task(fixture: dict[str, Any], orchestrator: Orchestrator) -> ExecutionResult:
    """Replay a normalized task fixture through the orchestrator."""
    return orchestrator.run(build_task_from_fixture(fixture))
