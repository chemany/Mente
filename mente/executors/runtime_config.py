"""Private runtime-config resolution for Mente-backed Codex execution."""

from __future__ import annotations

from copy import deepcopy
import json
from dataclasses import dataclass, field
from pathlib import Path

from kernel.codex.config import load_private_codex_config, load_private_model_settings
from mente.task_core.models import ExecutionRequest
from mente.executors.runtime_home import resolve_runtime_home

MENTE_DEFAULT_BASE_INSTRUCTIONS = (
    "You are Mente's coding agent. "
    "Inspect the workspace before changing code, then use the available tools and shell to complete the task end to end. "
    "If relevant skills are provided, read them first and follow the skill workflow before improvising. "
    "If skills specify scripts or commands, run the most direct one first. "
    "If that workflow is blocked, diagnose the concrete blocker, fix it, then resume the workflow. "
    "Keep edits minimal, correct, and consistent with the existing codebase. "
    "Do not overwrite user changes you did not make or use destructive git/file operations unless explicitly requested. "
    "Keep responses concise, action-oriented, and focused on the task result."
)
MENTE_CONTENT_BASE_INSTRUCTIONS = (
    "You are Mente's content and publishing agent. "
    "Gather only the minimum repository or workspace context needed to complete the requested draft, asset, or publication workflow. "
    "Prefer direct delivery over exploratory workspace scanning. "
    "Read provided skills first and follow their workflow before improvising. "
    "If skills specify scripts or commands, run the most direct one first. "
    "If the workflow is blocked, diagnose the concrete blocker, fix it, then resume the workflow. "
    "When a publishing tool or content skill is already provided, use it directly instead of rediscovering the workflow. "
    "Keep responses concise, action-oriented, and focused on the requested deliverable."
)
_CONTENT_PUBLISHING_TASK_PROFILE = "content_publishing"
_WECHAT_PUBLISHER_SKILL_REF = "media/wechat-publisher"
_CONTENT_PUBLISHING_MAX_RUNTIME_SECONDS = 300


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
    merged = load_private_codex_config(workspace=workspace)
    merged, explicit_subprocess_env = _apply_explicit_codex_runtime_settings(merged)
    merged, inherited_subprocess_env = _apply_mente_model_runtime_fallback(
        merged,
        load_private_model_settings(),
    )
    subprocess_env = dict(inherited_subprocess_env)
    subprocess_env.update(explicit_subprocess_env)

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


def adapt_runtime_config_for_request(
    runtime_config: RuntimeConfig,
    request: ExecutionRequest,
) -> RuntimeConfig:
    """Apply lightweight request-scoped runtime hints without mutating base config."""

    if not _is_content_publishing_request(request):
        return runtime_config

    codex_config = deepcopy(runtime_config.codex_config)
    existing_base_instructions = codex_config.get("base_instructions")
    if (
        not isinstance(existing_base_instructions, str)
        or not existing_base_instructions.strip()
        or existing_base_instructions == MENTE_DEFAULT_BASE_INSTRUCTIONS
    ):
        codex_config["base_instructions"] = MENTE_CONTENT_BASE_INSTRUCTIONS

    agents_config = codex_config.get("agents")
    if not isinstance(agents_config, dict):
        agents_config = {}
        codex_config["agents"] = agents_config
    agents_config.setdefault(
        "job_max_runtime_seconds",
        _CONTENT_PUBLISHING_MAX_RUNTIME_SECONDS,
    )

    return RuntimeConfig(
        runtime_home=runtime_config.runtime_home,
        ignore_user_config=runtime_config.ignore_user_config,
        ignore_rules=runtime_config.ignore_rules,
        codex_config=codex_config,
        subprocess_env=dict(runtime_config.subprocess_env),
    )


def _apply_explicit_codex_runtime_settings(
    merged: dict[str, object],
) -> tuple[dict[str, object], dict[str, str]]:
    if not merged:
        return {"base_instructions": MENTE_DEFAULT_BASE_INSTRUCTIONS}, {}

    resolved = dict(merged)
    subprocess_env: dict[str, str] = {}

    default_model = resolved.pop("default", None)
    if isinstance(default_model, str) and default_model.strip() and not isinstance(resolved.get("model"), str):
        resolved["model"] = default_model.strip()

    provider_label = resolved.pop("provider", None)
    if not isinstance(provider_label, str) or not provider_label.strip():
        provider_label = "Mente"
    else:
        provider_label = provider_label.strip()

    base_url = resolved.pop("base_url", None)
    if not isinstance(base_url, str) or not base_url.strip():
        base_url = ""
    else:
        base_url = base_url.strip()

    api_key = resolved.pop("api_key", None)
    if not isinstance(api_key, str) or not api_key.strip():
        api_key = ""
    else:
        api_key = api_key.strip()

    if _has_explicit_codex_provider_config(resolved):
        return _ensure_default_base_instructions(resolved), subprocess_env

    if not any((base_url, api_key)):
        return _ensure_default_base_instructions(resolved), subprocess_env

    model_providers = resolved.get("model_providers")
    if not isinstance(model_providers, dict):
        model_providers = {}
        resolved["model_providers"] = model_providers

    provider_config = model_providers.get("mente")
    if not isinstance(provider_config, dict):
        provider_config = {}

    provider_config.setdefault("name", provider_label)
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

    return _ensure_default_base_instructions(resolved), subprocess_env


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
        return _ensure_default_base_instructions(resolved), subprocess_env

    base_url = mente_model_settings.get("base_url", "")
    api_key = mente_model_settings.get("api_key", "")
    if not base_url and not api_key:
        return _ensure_default_base_instructions(resolved), subprocess_env

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

    return _ensure_default_base_instructions(resolved), subprocess_env


def _has_explicit_codex_provider_config(config: dict[str, object]) -> bool:
    return any(key in config for key in ("model_provider", "openai_base_url", "model_providers"))


def _ensure_default_base_instructions(config: dict[str, object]) -> dict[str, object]:
    resolved = dict(config)
    existing = resolved.get("base_instructions")
    if isinstance(existing, str) and existing.strip():
        return resolved
    resolved["base_instructions"] = MENTE_DEFAULT_BASE_INSTRUCTIONS
    return resolved


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


def _is_content_publishing_request(request: ExecutionRequest) -> bool:
    task_profile = str(request.metadata.get("task_profile") or "").strip()
    if task_profile == _CONTENT_PUBLISHING_TASK_PROFILE:
        return True
    return _WECHAT_PUBLISHER_SKILL_REF in {
        str(item).strip() for item in (request.skill_refs or []) if str(item).strip()
    }


def _format_config_override(key: str, value: object) -> str:
    return f"{key}={json.dumps(value, ensure_ascii=True)}"
