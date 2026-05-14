"""Shared helpers for user-defined model provider profiles.

Provider profiles live in ``config.yaml`` under ``providers:``. Secrets live
in ``.env`` via ``key_env`` so the dashboard, CLI, gateway, and TUI all read
one canonical shape without storing API keys in YAML.
"""

from __future__ import annotations

import re
import urllib.parse
from typing import Any, Dict, Iterable


MODEL_PROVIDER_API_MODES = {
    "chat_completions",
    "anthropic_messages",
    "codex_responses",
    "bedrock_converse",
}

MODEL_PROVIDER_ENV_RE = re.compile(r"^[A-Z_][A-Z0-9_]*$")
_MODEL_PROVIDER_SLUG_RE = re.compile(r"[^a-z0-9_-]+")


class ModelProviderProfileError(ValueError):
    """Raised when a model provider profile cannot be persisted."""


def as_nonempty_str(value: Any) -> str:
    return value.strip() if isinstance(value, str) and value.strip() else ""


def normalize_model_provider_slug(value: str) -> str:
    return _MODEL_PROVIDER_SLUG_RE.sub("-", value.strip().lower()).strip("-_")


def default_model_provider_key_env(slug: str) -> str:
    key = re.sub(r"[^A-Z0-9]+", "_", slug.upper()).strip("_")
    return f"{key}_API_KEY" if key else ""


def validate_model_provider_base_url(base_url: str) -> str:
    candidate = as_nonempty_str(base_url).rstrip("/")
    parsed = urllib.parse.urlparse(candidate)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ModelProviderProfileError("base_url must be an http(s) URL")
    return candidate


def _dedupe_models(default_model: str, models: Iterable[str] | None) -> list[str]:
    result: list[str] = []
    for item in [default_model, *(models or [])]:
        model_name = as_nonempty_str(item)
        if model_name and model_name not in result:
            result.append(model_name)
    return result


def save_model_provider_profile(
    *,
    name: str,
    base_url: str,
    default_model: str,
    api_key: str = "",
    slug: str = "",
    key_env: str = "",
    api_mode: str = "chat_completions",
    models: Iterable[str] | None = None,
    activate: bool = False,
) -> Dict[str, Any]:
    """Persist a provider profile and optional API key.

    Returns the saved provider entry plus its slug. API keys are written only
    to ``.env``; YAML stores the env var name in ``key_env``.
    """
    from hermes_cli.config import load_config, save_config, save_env_value

    cleaned_name = as_nonempty_str(name)
    cleaned_base_url = validate_model_provider_base_url(base_url)
    cleaned_default_model = as_nonempty_str(default_model)
    cleaned_slug = normalize_model_provider_slug(slug or cleaned_name)
    cleaned_api_mode = as_nonempty_str(api_mode) or "chat_completions"
    cleaned_key_env = as_nonempty_str(key_env).upper() or default_model_provider_key_env(cleaned_slug)

    if not cleaned_name:
        raise ModelProviderProfileError("name is required")
    if not cleaned_slug:
        raise ModelProviderProfileError("provider slug is required")
    if not cleaned_default_model:
        raise ModelProviderProfileError("default_model is required")
    if cleaned_api_mode not in MODEL_PROVIDER_API_MODES:
        raise ModelProviderProfileError("unsupported api_mode")
    if not cleaned_key_env or not MODEL_PROVIDER_ENV_RE.match(cleaned_key_env):
        raise ModelProviderProfileError("key_env must be an uppercase env var name")

    model_names = _dedupe_models(cleaned_default_model, models)
    if as_nonempty_str(api_key):
        save_env_value(cleaned_key_env, api_key.strip())

    cfg = load_config()
    providers = cfg.setdefault("providers", {})
    if not isinstance(providers, dict):
        providers = {}
        cfg["providers"] = providers

    entry = {
        "name": cleaned_name,
        "base_url": cleaned_base_url,
        "key_env": cleaned_key_env,
        "default_model": cleaned_default_model,
        "api_mode": cleaned_api_mode,
        "models": model_names,
    }
    providers[cleaned_slug] = entry

    if activate:
        model_cfg = cfg.get("model")
        if not isinstance(model_cfg, dict):
            model_cfg = {"default": model_cfg} if model_cfg else {}
            cfg["model"] = model_cfg
        model_cfg["provider"] = cleaned_slug
        model_cfg["default"] = cleaned_default_model
        model_cfg["base_url"] = cleaned_base_url
        model_cfg["api_mode"] = cleaned_api_mode
        model_cfg.pop("api_key", None)

    save_config(cfg)
    return {"slug": cleaned_slug, **entry}
