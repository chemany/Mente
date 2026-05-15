"""Shared deep-research path resolution for Mente-owned workflows."""

from __future__ import annotations

import os
from pathlib import Path

from hermes_constants import get_mente_home
import yaml


def resolve_deep_research_output_root() -> Path:
    """Return the configured deep-research artifact root."""
    mente_home = get_mente_home()
    config_path = mente_home / "config.yaml"
    configured = _read_configured_output_root(config_path)
    if configured:
        return configured
    return mente_home / "deep-research"


def resolve_private_runtime_write_roots(workspace: str | Path) -> list[Path]:
    """Return host paths that private Codex runtimes should be allowed to access."""
    roots: list[Path] = []
    for candidate in (
        Path(workspace).expanduser().resolve(),
        get_mente_home().resolve(),
        resolve_deep_research_output_root().resolve(),
    ):
        if candidate not in roots:
            roots.append(candidate)
    return roots


def _read_configured_output_root(config_path: Path) -> Path | None:
    if not config_path.exists():
        return None
    try:
        parsed = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return None
    if not isinstance(parsed, dict):
        return None
    mente_config = parsed.get("mente")
    if not isinstance(mente_config, dict):
        return None
    deep_research = mente_config.get("deep_research")
    if not isinstance(deep_research, dict):
        return None
    output_root = deep_research.get("output_root")
    if not isinstance(output_root, str) or not output_root.strip():
        return None
    normalized = Path(os.path.expandvars(output_root.strip())).expanduser()
    if not normalized.is_absolute():
        normalized = get_mente_home() / normalized
    return normalized.resolve()
