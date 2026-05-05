"""Private runtime-home resolution for Mente-managed kernel execution."""

from __future__ import annotations

import os
from pathlib import Path

from hermes_constants import get_mente_home

MENTE_CODEX_RUNTIME_HOME_ENV = "MENTE_CODEX_RUNTIME_HOME"


def resolve_runtime_home() -> Path:
    """Resolve the private runtime home used for Mente-backed Codex execution."""
    configured = os.getenv(MENTE_CODEX_RUNTIME_HOME_ENV, "").strip()
    if configured:
        return Path(configured).expanduser()
    return get_mente_home() / "codex"
