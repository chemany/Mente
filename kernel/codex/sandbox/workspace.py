"""Workspace helpers for isolated stateless Codex execution."""

from __future__ import annotations

import tempfile
from pathlib import Path


def prepare_isolated_workspace(prefix: str = "mente-codex-workdir-") -> Path:
    """Create the isolated workdir used as the transport cwd for stateless runs."""
    return Path(tempfile.mkdtemp(prefix=prefix)).resolve()
