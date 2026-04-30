"""Private runtime-config resolution for Mente-backed Codex execution."""

from __future__ import annotations

import json
import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from hermes_constants import get_hermes_home
from mente.executors.runtime_home import resolve_runtime_home


@dataclass(frozen=True)
class RuntimeConfig:
    """Resolved private runtime configuration for a Codex execution."""

    runtime_home: Path
    ignore_user_config: bool = True
    ignore_rules: bool = True
    codex_config: dict[str, object] = field(default_factory=dict)

    def to_codex_overrides(self) -> list[str]:
        """Flatten the private config model into Codex CLI override args."""
        return _flatten_config_overrides(self.codex_config)


def resolve_runtime_config(workspace: str | Path) -> RuntimeConfig:
    """Resolve the merged runtime config from system, profile, and workspace layers."""
    merged = _deep_merge(
        {},
        _load_toml(_resolve_profile_config_path()),
    )
    merged = _deep_merge(
        merged,
        _load_toml(_resolve_workspace_config_path(workspace)),
    )

    runtime_config = merged.pop("runtime", {})
    runtime_home = resolve_runtime_home()
    ignore_user_config = True
    ignore_rules = True
    if isinstance(runtime_config, dict):
        configured_home = runtime_config.get("home")
        if isinstance(configured_home, str) and configured_home.strip():
            runtime_home = Path(configured_home).expanduser()
        configured_ignore_user_config = runtime_config.get("ignore_user_config")
        if isinstance(configured_ignore_user_config, bool):
            ignore_user_config = configured_ignore_user_config
        configured_ignore_rules = runtime_config.get("ignore_rules")
        if isinstance(configured_ignore_rules, bool):
            ignore_rules = configured_ignore_rules

    return RuntimeConfig(
        runtime_home=runtime_home,
        ignore_user_config=ignore_user_config,
        ignore_rules=ignore_rules,
        codex_config=merged,
    )


def _resolve_profile_config_path() -> Path:
    configured = os.getenv("MENTE_CODEX_CONFIG_PATH", "").strip()
    if configured:
        return Path(configured).expanduser()
    return get_hermes_home() / "mente" / "config.toml"


def _resolve_workspace_config_path(workspace: str | Path) -> Path:
    configured = os.getenv("MENTE_CODEX_WORKSPACE_CONFIG_PATH", "").strip()
    if configured:
        return Path(configured).expanduser()
    return Path(workspace).expanduser() / ".mente" / "codex.toml"


def _load_toml(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    try:
        parsed = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return {}
    if not isinstance(parsed, dict):
        return {}
    return parsed


def _deep_merge(base: dict[str, object], overlay: dict[str, object]) -> dict[str, object]:
    merged = dict(base)
    for key, value in overlay.items():
        existing = merged.get(key)
        if isinstance(existing, dict) and isinstance(value, dict):
            merged[key] = _deep_merge(existing, value)
        else:
            merged[key] = value
    return merged


def _flatten_config_overrides(config: dict[str, object]) -> list[str]:
    overrides: list[str] = []
    for key in sorted(config):
        if not isinstance(key, str):
            continue
        overrides.extend(_flatten_value(key, config[key]))
    return overrides


def _flatten_value(prefix: str, value: object) -> list[str]:
    if isinstance(value, dict):
        overrides: list[str] = []
        for key in sorted(value):
            if not isinstance(key, str):
                continue
            overrides.extend(_flatten_value(f"{prefix}.{key}", value[key]))
        return overrides
    if isinstance(value, list):
        return [_format_config_override(prefix, value)]
    if isinstance(value, (str, bool, int, float)):
        return [_format_config_override(prefix, value)]
    return []


def _format_config_override(key: str, value: object) -> str:
    return f"{key}={json.dumps(value, ensure_ascii=True)}"
