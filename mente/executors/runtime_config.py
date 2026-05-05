"""Private runtime-config resolution for Mente-backed Codex execution."""

from __future__ import annotations

import json
import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from hermes_constants import get_mente_home
from mente.executors.runtime_home import resolve_runtime_home


@dataclass(frozen=True)
class RuntimeConfig:
    """Resolved private runtime configuration for a Codex execution."""

    runtime_home: Path
    ignore_user_config: bool = True
    ignore_rules: bool = True
    codex_config: dict[str, object] = field(default_factory=dict)
    subprocess_env: dict[str, str] = field(default_factory=dict)

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
    merged, subprocess_env = _apply_mente_model_runtime_fallback(
        merged,
        _load_mente_model_settings(),
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
        subprocess_env=subprocess_env,
    )


def _resolve_profile_config_path() -> Path:
    configured = os.getenv("MENTE_CODEX_CONFIG_PATH", "").strip()
    if configured:
        return Path(configured).expanduser()
    mente_home = get_mente_home()
    candidate = mente_home / "config.toml"
    return candidate


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


def _load_mente_model_settings() -> dict[str, str]:
    config_path = get_mente_home() / "config.yaml"
    if not config_path.exists():
        return {}
    try:
        parsed = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return {}
    if not isinstance(parsed, dict):
        return {}

    model = parsed.get("model")
    if not isinstance(model, dict):
        return {}

    settings: dict[str, str] = {}
    for key in ("default", "model", "provider", "base_url", "api_key"):
        value = model.get(key)
        if isinstance(value, str) and value.strip():
            settings[key] = value.strip()
    return settings


def _apply_mente_model_runtime_fallback(
    merged: dict[str, object],
    mente_model_settings: dict[str, str],
) -> tuple[dict[str, object], dict[str, str]]:
    if not mente_model_settings:
        return merged, {}

    resolved = dict(merged)
    subprocess_env: dict[str, str] = {}

    model_name = mente_model_settings.get("default") or mente_model_settings.get("model") or ""
    if model_name and not isinstance(resolved.get("model"), str):
        resolved["model"] = model_name

    if _has_explicit_codex_provider_config(resolved):
        return resolved, subprocess_env

    base_url = mente_model_settings.get("base_url", "")
    api_key = mente_model_settings.get("api_key", "")
    if not base_url and not api_key:
        return resolved, subprocess_env

    model_providers = resolved.get("model_providers")
    if not isinstance(model_providers, dict):
        model_providers = {}
        resolved["model_providers"] = model_providers

    provider_config = model_providers.get("mente")
    if not isinstance(provider_config, dict):
        provider_config = {}

    provider_config.setdefault("name", "Mente")
    if base_url:
        provider_config.setdefault("base_url", base_url)
    provider_config.setdefault("wire_api", "responses")
    provider_config.setdefault("env_key", "MENTE_CODEX_API_KEY")
    provider_config.setdefault("requires_openai_auth", False)

    model_providers["mente"] = provider_config
    resolved.setdefault("model_provider", "mente")

    if api_key:
        subprocess_env["MENTE_CODEX_API_KEY"] = api_key
    if base_url:
        subprocess_env["OPENAI_BASE_URL"] = base_url

    return resolved, subprocess_env


def _has_explicit_codex_provider_config(config: dict[str, object]) -> bool:
    return any(key in config for key in ("model_provider", "openai_base_url", "model_providers"))


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
