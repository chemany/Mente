"""Private Codex home resolution shared by Mente-owned integrations."""

from __future__ import annotations

import os
from pathlib import Path

from hermes_constants import get_mente_home

MENTE_CODEX_RUNTIME_HOME_ENV = "MENTE_CODEX_RUNTIME_HOME"


def resolve_private_codex_home() -> Path:
    """Resolve the Mente-owned Codex home, ignoring host public `.codex` state."""
    configured = os.getenv(MENTE_CODEX_RUNTIME_HOME_ENV, "").strip()
    if configured:
        return Path(configured).expanduser()
    return get_mente_home() / "codex"
