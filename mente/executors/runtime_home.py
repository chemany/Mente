"""Private runtime-home resolution for Mente-managed kernel execution."""

from __future__ import annotations

from pathlib import Path

from kernel.codex.home import resolve_private_codex_home


def resolve_runtime_home() -> Path:
    """Resolve the private runtime home used for Mente-backed Codex execution."""
    return resolve_private_codex_home()
