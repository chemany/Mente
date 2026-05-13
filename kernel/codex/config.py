"""Shared private Codex config loading for Mente-owned integrations."""

from __future__ import annotations

import os
import tomllib
from pathlib import Path

import yaml

from hermes_constants import get_mente_home


def load_private_codex_config(*, workspace: str | Path | None = None) -> dict[str, object]:
    """Load merged private Codex config, preferring YAML over legacy TOML."""
    merged = _load_profile_codex_layer()
    if workspace is not None:
        merged = _deep_merge(merged, _load_workspace_codex_layer(workspace))
    return merged


def load_private_codex_profile_config() -> dict[str, object]:
    """Load only the profile-level private Codex config."""
    return _load_profile_codex_layer()


def load_private_model_settings() -> dict[str, str]:
    """Load the profile-level global Mente model settings from config.yaml."""
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
    for key in ("default", "model", "provider", "base_url", "api_key", "api_mode"):
        value = model.get(key)
        if isinstance(value, str) and value.strip():
            settings[key] = value.strip()
    return settings


def resolve_private_codex_model_name(config: dict[str, object]) -> str | None:
    """Resolve the preferred model name from a private Codex config layer."""
    for key in ("model", "default"):
        value = config.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def migrate_legacy_private_codex_config(
    *,
    workspace: str | Path | None = None,
) -> dict[str, str]:
    """Copy legacy private Codex TOML config into the canonical YAML surface.

    This is intentionally non-destructive:
    - existing ``codex:`` YAML is never overwritten
    - legacy TOML files are left in place
    """
    results = {"profile": _migrate_profile_legacy_codex_layer()}
    if workspace is not None:
        results["workspace"] = _migrate_workspace_legacy_codex_layer(Path(workspace).expanduser())
    return results


def _load_profile_codex_layer() -> dict[str, object]:
    configured = os.getenv("MENTE_CODEX_CONFIG_PATH", "").strip()
    if configured:
        return _load_explicit_config_path(Path(configured).expanduser())
    mente_home = get_mente_home()
    return _load_yaml_first_layer(
        yaml_path=mente_home / "config.yaml",
        toml_path=mente_home / "config.toml",
    )


def _load_workspace_codex_layer(workspace: str | Path) -> dict[str, object]:
    configured = os.getenv("MENTE_CODEX_WORKSPACE_CONFIG_PATH", "").strip()
    if configured:
        return _load_explicit_config_path(Path(configured).expanduser())
    workspace_root = Path(workspace).expanduser()
    return _load_yaml_first_layer(
        yaml_path=workspace_root / ".mente" / "config.yaml",
        toml_path=workspace_root / ".mente" / "codex.toml",
    )


def _migrate_profile_legacy_codex_layer() -> str:
    mente_home = get_mente_home()
    return _migrate_legacy_toml_into_yaml_codex(
        yaml_path=mente_home / "config.yaml",
        toml_path=mente_home / "config.toml",
    )


def _migrate_workspace_legacy_codex_layer(workspace_root: Path) -> str:
    return _migrate_legacy_toml_into_yaml_codex(
        yaml_path=workspace_root / ".mente" / "config.yaml",
        toml_path=workspace_root / ".mente" / "codex.toml",
    )


def _load_yaml_first_layer(*, yaml_path: Path, toml_path: Path) -> dict[str, object]:
    yaml_config, yaml_is_authoritative = _load_codex_yaml_layer(yaml_path)
    if yaml_is_authoritative:
        return yaml_config
    return _load_toml(toml_path)


def _load_explicit_config_path(path: Path) -> dict[str, object]:
    suffix = path.suffix.lower()
    if suffix in (".yaml", ".yml"):
        config, _authoritative = _load_codex_yaml_layer(path)
        return config
    return _load_toml(path)


def _load_codex_yaml_layer(path: Path) -> tuple[dict[str, object], bool]:
    if not path.exists():
        return {}, False
    try:
        parsed = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return {}, True
    if not isinstance(parsed, dict):
        return {}, True
    codex = parsed.get("codex")
    if codex is None:
        return {}, False
    if not isinstance(codex, dict):
        return {}, True
    return codex, True


def _migrate_legacy_toml_into_yaml_codex(*, yaml_path: Path, toml_path: Path) -> str:
    legacy = _load_toml(toml_path)
    if not legacy:
        return "noop_no_legacy_toml"

    payload = _load_yaml_document(yaml_path)
    if "codex" in payload:
        return "skipped_existing_yaml_codex"

    payload["codex"] = legacy
    _write_yaml_document(yaml_path, payload)
    return "migrated"


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


def _load_yaml_document(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    try:
        parsed = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return {}
    if not isinstance(parsed, dict):
        return {}
    return parsed


def _write_yaml_document(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=False),
        encoding="utf-8",
    )


def _deep_merge(base: dict[str, object], overlay: dict[str, object]) -> dict[str, object]:
    merged = dict(base)
    for key, value in overlay.items():
        existing = merged.get(key)
        if isinstance(existing, dict) and isinstance(value, dict):
            merged[key] = _deep_merge(existing, value)
        else:
            merged[key] = value
    return merged
