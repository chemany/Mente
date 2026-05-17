"""Private runtime-config resolution for Mente-backed Codex execution."""

from __future__ import annotations

from copy import deepcopy
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

import yaml
from hermes_constants import get_mente_home
from kernel.codex.home import MENTE_CODEX_RUNTIME_HOME_ENV
from kernel.codex.config import load_private_codex_config, load_private_model_settings
from mente.task_core.models import ExecutionRequest
from mente.executors.runtime_home import resolve_runtime_home

MENTE_SELF_KNOWLEDGE = (
    "Mente is a self-hosted multi-agent assistant. "
    "The coordinator owns user turns, clarification, delegation, status, and worker control; "
    "background workers execute lane work such as engineering, research, writing, config_admin, and publishing. "
    "Worker jobs record task/job metadata, progress, terminal checkpoints, and controls in persisted state. "
    "Explicit skills route through skill ownership; unknown or cross-lane skill requests should clarify instead of guessing. "
    "Model switching uses config.yaml provider profiles plus .env secrets, shared by dashboard and CLI. "
    "It is safe to tell users that API keys are stored in <MENTE_HOME>/.env and provider metadata is stored in <MENTE_HOME>/config.yaml; "
    "share paths, env var names, and redacted key status, not secret values. "
    "Memory uses the unified Mente memory store with optional LLM memory review; do not create private per-runtime memories unless explicitly scoped."
)

MENTE_DEFAULT_BASE_INSTRUCTIONS = (
    "You are Mente's coding agent. "
    f"{MENTE_SELF_KNOWLEDGE} "
    "Inspect minimum relevant workspace context before changing code. "
    "For deterministic tasks with an explicit file, command, config key, or skill workflow, go directly to that target instead of broad exploration. "
    "For code-logic, default-value provenance, compatibility-sensitive, or multi-file changes, inspect relevant implementation first. "
    "If relevant skills are provided, follow the skill workflow before improvising. "
    "If skills specify scripts or commands, run the most direct one first. "
    "If blocked, diagnose the concrete blocker, fix it, then resume. "
    "Do not overwrite user changes or use destructive git/file operations unless explicitly requested. "
    "Keep responses concise, action-oriented, and focused on the task result."
)
MENTE_CONFIG_ADMIN_BASE_INSTRUCTIONS = (
    "You are Mente's operations and configuration agent. "
    f"{MENTE_SELF_KNOWLEDGE} "
    "Resolve the active config or auth path first, then read only the minimum directly relevant files. "
    "Prefer direct, surgical edits over broad workspace exploration. "
    "If the active source of truth, default precedence, or restart impact is unclear, inspect the relevant loader or service path before editing. "
    "If relevant skills are provided, read them first and follow the skill workflow before improvising. "
    "If the workflow names a concrete command, path lookup, or restart step, run that step first. "
    "Preserve unrelated settings, redact secrets in user-facing confirmations, and restart services only when the changed setting requires it. "
    "Keep responses concise, action-oriented, and focused on the requested change."
)
MENTE_CONVERSATION_BASE_INSTRUCTIONS = (
    "You are Mente's conversation agent. "
    f"{MENTE_SELF_KNOWLEDGE} "
    "Reply directly in the user's language, keep the answer concise, and avoid unnecessary process narration. "
    "Do not claim prior context, prior actions, or capabilities that are not provided in this turn. "
    "Use tools only when they are genuinely necessary to answer well."
)
MENTE_COORDINATOR_BASE_INSTRUCTIONS = (
    "You are Mente's coordinator. "
    f"{MENTE_SELF_KNOWLEDGE} "
    "Classify the user's request, decide whether to answer inline or delegate to a worker, and acknowledge the next step clearly. "
    "Handle clarifications, delegation framing, and lightweight status replies directly in the user's language. "
    "Do not perform heavy repository work, deep research, or lane-specific execution yourself unless the request is explicitly forced into inline coordinator mode. "
    "Keep replies concise, action-oriented, and focused on coordination outcomes."
)
MENTE_RESEARCH_BASE_INSTRUCTIONS = (
    "You are Mente's research agent. "
    f"{MENTE_SELF_KNOWLEDGE} "
    "Gather only the minimum evidence needed to answer the request well, then deliver the analysis directly. "
    "Prefer focused retrieval and synthesis over engineering-style repository exploration. "
    "Do not claim facts, sources, or prior context that are not actually available in this turn. "
    "Keep responses concise, structured, and decision-useful."
)
MENTE_DEEP_RESEARCH_BASE_INSTRUCTIONS = (
    "You are Mente's deep research execution agent. "
    f"{MENTE_SELF_KNOWLEDGE} "
    "Treat managed deep-research requests as delivery workflows, not lightweight synthesis replies. "
    "Read the provided skill first, run the most direct managed entrypoint first, and keep work scoped to the active workspace, skill root, and planned artifact paths. "
    "Generate the required report artifacts before replying when no concrete blocker prevents it. "
    "Do not stop at intermediate findings, partial plans, or workflow summaries when the report artifacts are still missing. "
    "If the workflow is blocked, diagnose the concrete blocker, fix it, and then resume the workflow. "
    "Keep responses concise, action-oriented, and focused on completed deliverables."
)
MENTE_WRITING_BASE_INSTRUCTIONS = (
    "You are Mente's writing agent. "
    f"{MENTE_SELF_KNOWLEDGE} "
    "Produce the requested draft, rewrite, or messaging deliverable directly. "
    "Prefer delivering concrete wording over process narration or exploratory analysis. "
    "Keep tone, language, and structure aligned with the user's request, and avoid claiming prior context that is not provided. "
    "Keep responses concise and focused on the requested output."
)
MENTE_CONTENT_BASE_INSTRUCTIONS = (
    "You are Mente's content and publishing agent. "
    f"{MENTE_SELF_KNOWLEDGE} "
    "Gather only the minimum repository or workspace context needed to complete the requested draft, asset, or publication workflow. "
    "Prefer direct delivery over exploratory workspace scanning. "
    "Read provided skills first and follow their workflow before improvising. "
    "If skills specify scripts or commands, run the most direct one first. "
    "If the workflow is blocked, diagnose the concrete blocker, fix it, then resume the workflow. "
    "When a publishing tool or content skill is already provided, use it directly instead of rediscovering the workflow. "
    "Keep responses concise, action-oriented, and focused on the requested deliverable."
)
_CONTENT_PUBLISHING_TASK_PROFILE = "content_publishing"
_COORDINATOR_PROFILE = "coordinator"
_CONFIG_ADMIN_TASK_PROFILE = "config_admin"
_DEEP_RESEARCH_TASK_PROFILE = "deep_research"
_DIRECTOR_LANE = "director"
_ENGINEERING_LANE = "engineering"
_RESEARCH_LANE = "research"
_WRITING_LANE = "writing"
_CONFIG_ADMIN_LANE = "config_admin"
_WECHAT_PUBLISHER_SKILL_REF = "media/wechat-publisher"
_MENTE_CONFIG_ADMIN_SKILL_REF = "software-development/mente-config-admin"
_CONTENT_PUBLISHING_MAX_RUNTIME_SECONDS = 300
MENTE_DEFAULT_AUTO_COMPACT_TOKEN_LIMIT = 160000
_SOUL_FILENAME_SUFFIX = ".md"
_BUILTIN_AGENT_DIR = Path(__file__).resolve().parent.parent / "agents"
_AGENT_REGISTRY_FILENAME = "registry.yaml"
_AGENT_METADATA_FILENAME = "agent.yaml"
_AGENT_SOUL_FILENAME = "soul.md"
_PREVIOUS_SELF_KNOWLEDGE_SNIPPETS = {
    "Model switching uses config.yaml provider profiles plus .env secrets, shared by dashboard and CLI. "
    "Memory uses the unified Mente memory store with optional LLM memory review; do not create private per-runtime memories unless explicitly scoped."
}
_KNOWN_LEGACY_BUILTIN_SOULS = {
    "You are Mente's conversation agent. Reply directly in the user's language, keep the answer concise, and avoid unnecessary process narration. Do not claim prior context, prior actions, or capabilities that are not provided in this turn. Use tools only when they are genuinely necessary to answer well.",
    "You are Mente's coding agent. Inspect only the minimum relevant workspace context before changing code. For deterministic tasks with an explicit file, command, config key, or skill workflow, go directly to that target instead of broad exploration. For code-logic, default-value provenance, compatibility-sensitive, or multi-file behavior changes, inspect the relevant implementation and affected files before editing. If relevant skills are provided, read them first and follow the skill workflow before improvising. If skills specify scripts or commands, run the most direct one first. If that workflow is blocked, diagnose the concrete blocker, fix it, then resume the workflow. Keep edits minimal, correct, and consistent with the existing codebase. Do not overwrite user changes you did not make or use destructive git/file operations unless explicitly requested. Keep responses concise, action-oriented, and focused on the task result.",
    "You are Mente's research agent. Gather only the minimum evidence needed to answer the request well, then deliver the analysis directly. Prefer focused retrieval and synthesis over engineering-style repository exploration. Do not claim facts, sources, or prior context that are not actually available in this turn. Keep responses concise, structured, and decision-useful.",
    "You are Mente's writing agent. Produce the requested draft, rewrite, or messaging deliverable directly. Prefer delivering concrete wording over process narration or exploratory analysis. Keep tone, language, and structure aligned with the user's request, and avoid claiming prior context that is not provided. Keep responses concise and focused on the requested output.",
    "You are Mente's operations and configuration agent. Resolve the active config or auth path first, then read only the minimum directly relevant files. Prefer direct, surgical edits over broad workspace exploration. If the active source of truth, default precedence, or restart impact is unclear, inspect the relevant loader or service path before editing. If relevant skills are provided, read them first and follow the skill workflow before improvising. If the workflow names a concrete command, path lookup, or restart step, run that step first. Preserve unrelated settings, redact secrets in user-facing confirmations, and restart services only when the changed setting requires it. Keep responses concise, action-oriented, and focused on the requested change.",
    "You are Mente's content and publishing agent. Gather only the minimum repository or workspace context needed to complete the requested draft, asset, or publication workflow. Prefer direct delivery over exploratory workspace scanning. Read provided skills first and follow their workflow before improvising. If skills specify scripts or commands, run the most direct one first. If the workflow is blocked, diagnose the concrete blocker, fix it, then resume the workflow. When a publishing tool or content skill is already provided, use it directly instead of rediscovering the workflow. Keep responses concise, action-oriented, and focused on the requested deliverable.",
    "You are Mente's coding agent. Mente is a self-hosted multi-agent assistant. The coordinator owns user turns, clarification, delegation, status, and worker control; background workers execute lane work such as engineering, research, writing, config_admin, and publishing. Worker jobs record task/job metadata, progress, terminal checkpoints, and controls in persisted state. Explicit skills route through skill ownership; unknown or cross-lane skill requests should clarify instead of guessing. Model switching uses config.yaml provider profiles plus .env secrets, shared by dashboard and CLI. It is safe to tell users that API keys are stored in <MENTE_HOME>/.env and provider metadata is stored in <MENTE_HOME>/config.yaml; share paths, env var names, and redacted key status, not secret values. Memory uses the unified Mente memory store with optional LLM memory review; do not create private per-runtime memories unless explicitly scoped. Inspect only the minimum relevant workspace context before changing code. For deterministic tasks with an explicit file, command, config key, or skill workflow, go directly to that target instead of broad exploration. For code-logic, default-value provenance, compatibility-sensitive, or multi-file behavior changes, inspect the relevant implementation and affected files before editing. If relevant skills are provided, read them first and follow the skill workflow before improvising. If skills specify scripts or commands, run the most direct one first. If that workflow is blocked, diagnose the concrete blocker, fix it, then resume the workflow. Keep edits minimal, correct, and consistent with the existing codebase. Do not overwrite user changes you did not make or use destructive git/file operations unless explicitly requested. Keep responses concise, action-oriented, and focused on the task result.",
}


@dataclass(frozen=True)
class ModelRuntime:
    """Resolved model transport metadata for one Mente-owned runtime."""

    model: str | None = None
    provider: str | None = None
    base_url: str | None = None
    api_mode: str = "codex_responses"
    source: str = "default"

    @property
    def requires_responses_compat_proxy(self) -> bool:
        return self.api_mode != "codex_responses"

    def to_metadata(self) -> dict[str, str]:
        metadata = {
            "api_mode": self.api_mode,
            "source": self.source,
        }
        if self.model:
            metadata["model"] = self.model
        if self.provider:
            metadata["provider"] = self.provider
        if self.base_url:
            metadata["base_url"] = self.base_url
        return metadata


@dataclass(frozen=True)
class RuntimeConfig:
    """Resolved private runtime configuration for a Codex execution."""

    runtime_home: Path
    runtime_home_is_default: bool = False
    ignore_user_config: bool = True
    ignore_rules: bool = True
    sandbox: str | None = None
    approval_policy: str | None = None
    skip_git_repo_check: bool | None = None
    color: str | None = None
    model_runtime: ModelRuntime = field(default_factory=ModelRuntime)
    codex_config: dict[str, object] = field(default_factory=dict)
    profile_overrides: dict[str, dict[str, object]] = field(default_factory=dict)
    subprocess_env: dict[str, str] = field(default_factory=dict)

    def to_codex_overrides(self) -> list[str]:
        """Flatten the private config model into Codex CLI override args."""
        return _flatten_config_overrides(self.codex_config)


def resolve_runtime_config(workspace: str | Path) -> RuntimeConfig:
    """Resolve the merged runtime config from system, profile, and workspace layers."""
    _ensure_mente_home_agent_registry(get_mente_home())
    mente_model_settings = load_private_model_settings()
    merged = load_private_codex_config(workspace=workspace)
    merged, explicit_subprocess_env, explicit_model_settings = _apply_explicit_codex_runtime_settings(merged)
    merged, inherited_subprocess_env = _apply_mente_model_runtime_fallback(
        merged,
        mente_model_settings,
    )
    model_runtime = _resolve_model_runtime(
        merged,
        explicit_model_settings=explicit_model_settings,
        mente_model_settings=mente_model_settings,
    )
    merged, profile_overrides = _extract_profile_overrides(merged)
    subprocess_env = dict(inherited_subprocess_env)
    subprocess_env.update(explicit_subprocess_env)

    runtime_config = merged.pop("runtime", {})
    runtime_home = resolve_runtime_home()
    runtime_home_is_default = not bool(os.getenv(MENTE_CODEX_RUNTIME_HOME_ENV, "").strip())
    ignore_user_config = True
    ignore_rules = True
    sandbox: str | None = None
    approval_policy: str | None = None
    skip_git_repo_check: bool | None = None
    color: str | None = None
    if isinstance(runtime_config, dict):
        configured_home = runtime_config.get("home")
        if isinstance(configured_home, str) and configured_home.strip():
            runtime_home = Path(configured_home).expanduser()
            runtime_home_is_default = False
        configured_ignore_user_config = runtime_config.get("ignore_user_config")
        if isinstance(configured_ignore_user_config, bool):
            ignore_user_config = configured_ignore_user_config
        configured_ignore_rules = runtime_config.get("ignore_rules")
        if isinstance(configured_ignore_rules, bool):
            ignore_rules = configured_ignore_rules
        configured_sandbox = runtime_config.get("sandbox")
        if isinstance(configured_sandbox, str) and configured_sandbox.strip():
            sandbox = configured_sandbox.strip()
        configured_approval_policy = runtime_config.get("approval_policy")
        if isinstance(configured_approval_policy, str) and configured_approval_policy.strip():
            approval_policy = configured_approval_policy.strip()
        configured_skip_git_repo_check = runtime_config.get("skip_git_repo_check")
        if isinstance(configured_skip_git_repo_check, bool):
            skip_git_repo_check = configured_skip_git_repo_check
        configured_color = runtime_config.get("color")
        if isinstance(configured_color, str) and configured_color.strip():
            color = configured_color.strip()

    return RuntimeConfig(
        runtime_home=runtime_home,
        runtime_home_is_default=runtime_home_is_default,
        ignore_user_config=ignore_user_config,
        ignore_rules=ignore_rules,
        sandbox=sandbox,
        approval_policy=approval_policy,
        skip_git_repo_check=skip_git_repo_check,
        color=color,
        model_runtime=model_runtime,
        codex_config=merged,
        profile_overrides=profile_overrides,
        subprocess_env=subprocess_env,
    )


def adapt_runtime_config_for_request(
    runtime_config: RuntimeConfig,
    request: ExecutionRequest,
) -> RuntimeConfig:
    """Apply lightweight request-scoped runtime hints without mutating base config."""

    target_base_instructions: str | None = None
    job_max_runtime_seconds: int | None = None
    soul_name = _resolve_request_soul_name(request)
    runtime_home = _resolve_request_runtime_home(runtime_config, soul_name)

    if not _is_coordinator_request(request) and _is_content_publishing_request(request):
        job_max_runtime_seconds = _CONTENT_PUBLISHING_MAX_RUNTIME_SECONDS

    codex_config = deepcopy(runtime_config.codex_config)
    profile_override = _resolve_request_profile_override(runtime_config, request)
    if profile_override:
        codex_config = _deep_merge_config(codex_config, profile_override)

    target_base_instructions = _resolve_request_base_instructions(
        runtime_config=runtime_config,
        request=request,
        soul_name=soul_name,
        codex_config=codex_config,
    )
    if (
        target_base_instructions is None
        and job_max_runtime_seconds is None
        and runtime_home == runtime_config.runtime_home
    ):
        return runtime_config
    if target_base_instructions is not None:
        codex_config["base_instructions"] = target_base_instructions

    if job_max_runtime_seconds is not None:
        agents_config = codex_config.get("agents")
        if not isinstance(agents_config, dict):
            agents_config = {}
            codex_config["agents"] = agents_config
        agents_config.setdefault(
            "job_max_runtime_seconds",
            job_max_runtime_seconds,
        )

    return RuntimeConfig(
        runtime_home=runtime_home,
        runtime_home_is_default=runtime_config.runtime_home_is_default,
        ignore_user_config=runtime_config.ignore_user_config,
        ignore_rules=runtime_config.ignore_rules,
        sandbox=runtime_config.sandbox,
        approval_policy=runtime_config.approval_policy,
        skip_git_repo_check=runtime_config.skip_git_repo_check,
        color=runtime_config.color,
        model_runtime=runtime_config.model_runtime,
        codex_config=codex_config,
        profile_overrides=runtime_config.profile_overrides,
        subprocess_env=dict(runtime_config.subprocess_env),
    )


def _uses_thin_conversation_prompt(request: ExecutionRequest) -> bool:
    from mente.executors.prompting import uses_thin_conversation_prompt

    return uses_thin_conversation_prompt(request)


def _resolve_request_base_instructions(
    *,
    runtime_config: RuntimeConfig,
    request: ExecutionRequest,
    soul_name: str | None,
    codex_config: dict[str, object],
) -> str | None:
    if _has_explicit_global_base_instructions(runtime_config.codex_config):
        return None

    if soul_name:
        mente_home_soul = _load_mente_home_soul(soul_name)
        if mente_home_soul is not None:
            return mente_home_soul

    existing_base_instructions = codex_config.get("base_instructions")
    if isinstance(existing_base_instructions, str) and existing_base_instructions.strip():
        if existing_base_instructions != MENTE_DEFAULT_BASE_INSTRUCTIONS:
            return existing_base_instructions

    if soul_name and not _should_use_request_scoped_base_instructions(request, soul_name):
        builtin_soul = _load_builtin_soul(soul_name)
        if builtin_soul is not None:
            return builtin_soul

    return _legacy_base_instructions_for_request(request)


def _has_explicit_global_base_instructions(codex_config: dict[str, object]) -> bool:
    existing = codex_config.get("base_instructions")
    return (
        isinstance(existing, str)
        and existing.strip()
        and existing != MENTE_DEFAULT_BASE_INSTRUCTIONS
    )


def _resolve_request_soul_name(request: ExecutionRequest) -> str | None:
    if _is_coordinator_request(request):
        return _COORDINATOR_PROFILE
    task_profile = str(request.metadata.get("task_profile") or "").strip().lower()
    if task_profile == _DEEP_RESEARCH_TASK_PROFILE:
        return _DEEP_RESEARCH_TASK_PROFILE
    if _is_content_publishing_request(request):
        return _CONTENT_PUBLISHING_TASK_PROFILE
    if _is_config_admin_request(request):
        return _CONFIG_ADMIN_TASK_PROFILE

    request_lane = _resolved_request_lane(request)
    if request_lane in {
        _DIRECTOR_LANE,
        _ENGINEERING_LANE,
        _RESEARCH_LANE,
        _WRITING_LANE,
        _CONFIG_ADMIN_LANE,
    }:
        return request_lane
    if _uses_thin_conversation_prompt(request):
        return _DIRECTOR_LANE
    return _ENGINEERING_LANE


def _should_use_request_scoped_base_instructions(
    request: ExecutionRequest,
    soul_name: str,
) -> bool:
    if soul_name == _COORDINATOR_PROFILE and _is_coordinator_request(request):
        return True
    return (
        soul_name == _DEEP_RESEARCH_TASK_PROFILE
        and str(request.metadata.get("task_profile") or "").strip().lower() == _DEEP_RESEARCH_TASK_PROFILE
    )


def _load_mente_home_soul(name: str) -> str | None:
    mente_home = get_mente_home()
    registry = _ensure_mente_home_agent_registry(mente_home)
    agent_id = _resolve_agent_id_for_soul_name(name, registry)
    if agent_id:
        soul_path = mente_home / "agents" / agent_id / _AGENT_SOUL_FILENAME
        text = _read_soul_file(soul_path)
        builtin_text = _read_soul_file(_BUILTIN_AGENT_DIR / agent_id / _AGENT_SOUL_FILENAME)
        if text is not None and text != builtin_text:
            return text
    return None


def _load_builtin_soul(name: str) -> str | None:
    registry = _load_agent_registry(_BUILTIN_AGENT_DIR / _AGENT_REGISTRY_FILENAME)
    agent_id = _resolve_agent_id_for_soul_name(name, registry)
    if agent_id:
        soul_path = _BUILTIN_AGENT_DIR / agent_id / _AGENT_SOUL_FILENAME
        text = _read_soul_file(soul_path)
        if text is not None:
            return text
    return None


def _resolve_request_runtime_home(
    runtime_config: RuntimeConfig,
    soul_name: str | None,
) -> Path:
    if not runtime_config.runtime_home_is_default or not soul_name:
        return runtime_config.runtime_home
    mente_home = get_mente_home()
    registry = _ensure_mente_home_agent_registry(mente_home)
    agent_id = _resolve_agent_id_for_soul_name(soul_name, registry)
    if not agent_id:
        return runtime_config.runtime_home
    runtime_home = _agent_runtime_home(mente_home, agent_id)
    runtime_home.mkdir(parents=True, exist_ok=True)
    return runtime_home


def _ensure_mente_home_agent_registry(mente_home: Path) -> dict[str, object]:
    builtin_registry = _load_agent_registry(_BUILTIN_AGENT_DIR / _AGENT_REGISTRY_FILENAME)
    agents_root = mente_home / "agents"
    registry_path = agents_root / _AGENT_REGISTRY_FILENAME
    agents_root.mkdir(parents=True, exist_ok=True)
    if not registry_path.exists():
        registry_path.write_text(
            yaml.safe_dump(builtin_registry, sort_keys=False, allow_unicode=False),
            encoding="utf-8",
        )
    registry = _load_agent_registry(registry_path)
    if not registry:
        registry = builtin_registry
    _migrate_legacy_souls_to_agent_storage(
        mente_home=mente_home,
        registry=registry,
    )
    _seed_mente_home_agent_directories(
        mente_home=mente_home,
        registry=registry,
    )
    return registry


def _seed_mente_home_agent_directories(
    *,
    mente_home: Path,
    registry: dict[str, object],
) -> None:
    agents_root = mente_home / "agents"
    agents_config = registry.get("agents")
    if not isinstance(agents_config, dict):
        return

    for agent_id, agent_config in agents_config.items():
        if not isinstance(agent_id, str):
            continue
        if not isinstance(agent_config, dict):
            agent_config = {}
        agent_dir = agents_root / agent_id
        agent_dir.mkdir(parents=True, exist_ok=True)
        _agent_runtime_home(mente_home, agent_id).mkdir(parents=True, exist_ok=True)

        agent_metadata_path = agent_dir / _AGENT_METADATA_FILENAME
        if not agent_metadata_path.exists():
            metadata = dict(agent_config)
            metadata.setdefault("id", agent_id)
            agent_metadata_path.write_text(
                yaml.safe_dump(metadata, sort_keys=False, allow_unicode=False),
                encoding="utf-8",
            )

        soul_path = agent_dir / _AGENT_SOUL_FILENAME
        builtin_soul_path = _BUILTIN_AGENT_DIR / agent_id / _AGENT_SOUL_FILENAME
        builtin_soul = _read_soul_file(builtin_soul_path)
        if soul_path.exists():
            existing_soul = _read_soul_file(soul_path)
            if (
                (
                    existing_soul in _KNOWN_LEGACY_BUILTIN_SOULS
                    or _is_previous_builtin_self_knowledge_soul(existing_soul)
                )
                and builtin_soul is not None
                and existing_soul != builtin_soul
            ):
                soul_path.write_text(builtin_soul, encoding="utf-8")
            continue
        if builtin_soul is not None:
            soul_path.write_text(builtin_soul, encoding="utf-8")


def _is_previous_builtin_self_knowledge_soul(text: str | None) -> bool:
    if not text:
        return False
    if not text.startswith("You are Mente's "):
        return False
    return any(snippet in text for snippet in _PREVIOUS_SELF_KNOWLEDGE_SNIPPETS)


def _load_agent_registry(path: Path) -> dict[str, object]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    if isinstance(raw, dict):
        return raw
    return {}


def _agent_runtime_home(mente_home: Path, agent_id: str) -> Path:
    return mente_home / "runtime" / "agents" / agent_id / "codex"


def _resolve_agent_id_for_soul_name(name: str, registry: dict[str, object]) -> str | None:
    if not name:
        return None
    task_profiles = registry.get("task_profiles")
    if isinstance(task_profiles, dict):
        task_profile_agent = task_profiles.get(name)
        if isinstance(task_profile_agent, str) and task_profile_agent.strip():
            return task_profile_agent.strip()
    lanes = registry.get("lanes")
    if isinstance(lanes, dict):
        lane_agent = lanes.get(name)
        if isinstance(lane_agent, str) and lane_agent.strip():
            return lane_agent.strip()
    return None


def _migrate_legacy_souls_to_agent_storage(
    *,
    mente_home: Path,
    registry: dict[str, object],
) -> None:
    legacy_souls_dir = mente_home / "souls"
    if not legacy_souls_dir.is_dir():
        return

    migrated_any = False
    for legacy_soul_path in sorted(legacy_souls_dir.glob(f"*{_SOUL_FILENAME_SUFFIX}")):
        soul_name = legacy_soul_path.stem.strip()
        if not soul_name:
            continue
        legacy_soul = _read_soul_file(legacy_soul_path)
        agent_id = _resolve_agent_id_for_soul_name(soul_name, registry)
        if legacy_soul is None or not agent_id:
            continue
        agent_dir = mente_home / "agents" / agent_id
        agent_dir.mkdir(parents=True, exist_ok=True)
        soul_path = agent_dir / _AGENT_SOUL_FILENAME
        soul_path.write_text(legacy_soul, encoding="utf-8")
        legacy_soul_path.unlink(missing_ok=True)
        migrated_any = True

    if not migrated_any:
        return
    try:
        legacy_souls_dir.rmdir()
    except OSError:
        pass


def _read_soul_file(path: Path) -> str | None:
    try:
        text = path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return None
    if not text:
        return None
    return text


def _legacy_base_instructions_for_request(request: ExecutionRequest) -> str | None:
    if _is_coordinator_request(request):
        return MENTE_COORDINATOR_BASE_INSTRUCTIONS
    if str(request.metadata.get("task_profile") or "").strip().lower() == _DEEP_RESEARCH_TASK_PROFILE:
        return MENTE_DEEP_RESEARCH_BASE_INSTRUCTIONS
    if _is_content_publishing_request(request):
        return MENTE_CONTENT_BASE_INSTRUCTIONS
    if _is_config_admin_request(request):
        return MENTE_CONFIG_ADMIN_BASE_INSTRUCTIONS

    request_lane = _resolved_request_lane(request)
    if request_lane == _RESEARCH_LANE:
        return MENTE_RESEARCH_BASE_INSTRUCTIONS
    if request_lane == _WRITING_LANE:
        return MENTE_WRITING_BASE_INSTRUCTIONS
    if request_lane == _DIRECTOR_LANE or _uses_thin_conversation_prompt(request):
        return MENTE_CONVERSATION_BASE_INSTRUCTIONS
    return MENTE_DEFAULT_BASE_INSTRUCTIONS


def _apply_explicit_codex_runtime_settings(
    merged: dict[str, object],
) -> tuple[dict[str, object], dict[str, str], dict[str, str]]:
    if not merged:
        return _ensure_default_runtime_defaults({}), {}, {}

    resolved = dict(merged)
    subprocess_env: dict[str, str] = {}
    extracted_settings: dict[str, str] = {}

    default_model = resolved.pop("default", None)
    if isinstance(default_model, str) and default_model.strip():
        extracted_settings["default"] = default_model.strip()
        if not isinstance(resolved.get("model"), str):
            resolved["model"] = default_model.strip()

    provider_label = resolved.pop("provider", None)
    if not isinstance(provider_label, str) or not provider_label.strip():
        provider_label = ""
    else:
        provider_label = provider_label.strip()
        extracted_settings["provider"] = provider_label

    base_url = resolved.pop("base_url", None)
    if not isinstance(base_url, str) or not base_url.strip():
        base_url = ""
    else:
        base_url = base_url.strip()
        extracted_settings["base_url"] = base_url

    api_key = resolved.pop("api_key", None)
    if not isinstance(api_key, str) or not api_key.strip():
        api_key = ""
    else:
        api_key = api_key.strip()
        extracted_settings["api_key"] = api_key

    api_mode = _normalize_api_mode(resolved.pop("api_mode", None))
    if api_mode is not None:
        extracted_settings["api_mode"] = api_mode

    if _has_explicit_codex_provider_config(resolved):
        if api_key:
            subprocess_env["MENTE_CODEX_API_KEY"] = api_key
        return _ensure_default_runtime_defaults(resolved), subprocess_env, extracted_settings

    if not any((base_url, api_key)):
        return _ensure_default_runtime_defaults(resolved), subprocess_env, extracted_settings

    if api_key:
        subprocess_env["MENTE_CODEX_API_KEY"] = api_key

    resolved_api_mode = _resolve_api_mode(
        explicit_api_mode=api_mode,
        provider=provider_label,
        base_url=base_url,
        model=_resolve_model_name(resolved),
    )
    if resolved_api_mode != "codex_responses":
        return _ensure_default_runtime_defaults(resolved), subprocess_env, extracted_settings

    model_providers = resolved.get("model_providers")
    if not isinstance(model_providers, dict):
        model_providers = {}
        resolved["model_providers"] = model_providers

    provider_config = model_providers.get("mente")
    if not isinstance(provider_config, dict):
        provider_config = {}

    provider_config.setdefault("name", provider_label or "Mente")
    if base_url:
        provider_config.setdefault("base_url", base_url)
    provider_config.setdefault("wire_api", "responses")
    provider_config.setdefault("env_key", "MENTE_CODEX_API_KEY")
    provider_config.setdefault("requires_openai_auth", False)

    model_providers["mente"] = provider_config
    resolved.setdefault("model_provider", "mente")

    if base_url:
        subprocess_env["OPENAI_BASE_URL"] = base_url

    return _ensure_default_runtime_defaults(resolved), subprocess_env, extracted_settings


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
        return _ensure_default_runtime_defaults(resolved), subprocess_env

    base_url = mente_model_settings.get("base_url", "")
    provider = mente_model_settings.get("provider", "")
    api_key = mente_model_settings.get("api_key", "") or _resolve_provider_api_key_from_env(provider)
    if not base_url and not api_key:
        return _ensure_default_runtime_defaults(resolved), subprocess_env

    if api_key:
        subprocess_env["MENTE_CODEX_API_KEY"] = api_key

    resolved_api_mode = _resolve_api_mode(
        explicit_api_mode=mente_model_settings.get("api_mode"),
        provider=mente_model_settings.get("provider"),
        base_url=base_url,
        model=_resolve_model_name(resolved),
    )
    if resolved_api_mode != "codex_responses":
        return _ensure_default_runtime_defaults(resolved), subprocess_env

    model_providers = resolved.get("model_providers")
    if not isinstance(model_providers, dict):
        model_providers = {}
        resolved["model_providers"] = model_providers

    provider_config = model_providers.get("mente")
    if not isinstance(provider_config, dict):
        provider_config = {}

    provider_config.setdefault("name", mente_model_settings.get("provider") or "Mente")
    if base_url:
        provider_config.setdefault("base_url", base_url)
    provider_config.setdefault("wire_api", "responses")
    provider_config.setdefault("env_key", "MENTE_CODEX_API_KEY")
    provider_config.setdefault("requires_openai_auth", False)

    model_providers["mente"] = provider_config
    resolved.setdefault("model_provider", "mente")

    if base_url:
        subprocess_env["OPENAI_BASE_URL"] = base_url

    return _ensure_default_runtime_defaults(resolved), subprocess_env


def _resolve_provider_api_key_from_env(provider: str | None) -> str:
    provider_id = _clean_optional_str(provider)
    if not provider_id:
        return ""

    try:
        from hermes_cli.auth import PROVIDER_REGISTRY
    except Exception:
        return ""

    pconfig = PROVIDER_REGISTRY.get(provider_id)
    if pconfig is not None:
        for env_name in getattr(pconfig, "api_key_env_vars", ()) or ():
            value = _get_mente_env_value(str(env_name))
            if isinstance(value, str) and value.strip():
                return value.strip()

    configured_provider_key = _resolve_user_defined_provider_api_key(provider_id)
    if configured_provider_key:
        return configured_provider_key
    return ""


def _resolve_user_defined_provider_api_key(provider_id: str) -> str:
    config_path = get_mente_home() / "config.yaml"
    if not config_path.exists():
        return ""

    try:
        parsed = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return ""

    if not isinstance(parsed, dict):
        return ""
    providers = parsed.get("providers")
    if not isinstance(providers, dict):
        return ""

    entry = providers.get(provider_id)
    if not isinstance(entry, dict):
        return ""

    inline_api_key = _clean_optional_str(entry.get("api_key"))
    if inline_api_key:
        return inline_api_key

    key_env = _clean_optional_str(entry.get("key_env"))
    if not key_env:
        return ""

    value = _get_mente_env_value(key_env)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return ""


def _get_mente_env_value(key: str) -> str | None:
    value = os.environ.get(key)
    if isinstance(value, str) and value.strip():
        return value

    env_path = get_mente_home() / ".env"
    try:
        lines = env_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None

    prefix = f"{key}="
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if not line.startswith(prefix):
            continue
        return line[len(prefix):].strip().strip('"\'')
    return None


def _resolve_model_runtime(
    config: dict[str, object],
    *,
    explicit_model_settings: dict[str, str],
    mente_model_settings: dict[str, str],
) -> ModelRuntime:
    model_name = _resolve_model_name(config)
    explicit_runtime = _build_model_runtime_from_settings(
        explicit_model_settings,
        model_name=model_name,
        source="codex_settings",
    )
    if explicit_runtime is not None:
        return explicit_runtime

    codex_runtime = _build_model_runtime_from_codex_config(config)
    if codex_runtime is not None:
        return codex_runtime

    fallback_runtime = _build_model_runtime_from_settings(
        mente_model_settings,
        model_name=model_name,
        source="mente_model_settings",
    )
    if fallback_runtime is not None:
        return fallback_runtime

    return ModelRuntime(
        model=model_name,
        source="default",
    )


def _build_model_runtime_from_settings(
    settings: dict[str, str],
    *,
    model_name: str | None,
    source: str,
) -> ModelRuntime | None:
    provider = _clean_optional_str(settings.get("provider"))
    base_url = _clean_optional_str(settings.get("base_url"))
    explicit_api_mode = _normalize_api_mode(settings.get("api_mode"))
    resolved_model = model_name or _clean_optional_str(settings.get("model")) or _clean_optional_str(
        settings.get("default")
    )
    if not any((provider, base_url, explicit_api_mode)):
        return None
    return ModelRuntime(
        model=resolved_model,
        provider=provider,
        base_url=base_url,
        api_mode=_resolve_api_mode(
            explicit_api_mode=explicit_api_mode,
            provider=provider,
            base_url=base_url,
            model=resolved_model,
        ),
        source=source,
    )


def _build_model_runtime_from_codex_config(config: dict[str, object]) -> ModelRuntime | None:
    model_name = _resolve_model_name(config)
    provider = _clean_optional_str(config.get("model_provider"))
    base_url = _clean_optional_str(config.get("openai_base_url"))
    explicit_api_mode = None

    model_providers = config.get("model_providers")
    if provider and isinstance(model_providers, dict):
        provider_config = model_providers.get(provider)
        if isinstance(provider_config, dict):
            provider = _clean_optional_str(provider_config.get("name")) or provider
            base_url = _clean_optional_str(provider_config.get("base_url")) or base_url
            explicit_api_mode = _normalize_api_mode(provider_config.get("wire_api"))

    if not any((provider, base_url, explicit_api_mode)):
        return None
    return ModelRuntime(
        model=model_name,
        provider=provider,
        base_url=base_url,
        api_mode=_resolve_api_mode(
            explicit_api_mode=explicit_api_mode,
            provider=provider,
            base_url=base_url,
            model=model_name,
        ),
        source="codex_config",
    )


def _has_explicit_codex_provider_config(config: dict[str, object]) -> bool:
    return any(key in config for key in ("model_provider", "openai_base_url", "model_providers"))


def _resolve_model_name(config: dict[str, object]) -> str | None:
    return _clean_optional_str(config.get("model")) or _clean_optional_str(config.get("default"))


def _clean_optional_str(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    candidate = value.strip()
    return candidate or None


def _normalize_api_mode(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower().replace("-", "_")
    if not normalized:
        return None
    aliases = {
        "responses": "codex_responses",
        "codex_responses": "codex_responses",
        "chat": "chat_completions",
        "chat_completions": "chat_completions",
        "openai_chat": "chat_completions",
        "anthropic": "anthropic_messages",
        "anthropic_messages": "anthropic_messages",
    }
    return aliases.get(normalized)


def _resolve_api_mode(
    *,
    explicit_api_mode: str | None,
    provider: str | None,
    base_url: str | None,
    model: str | None,
) -> str:
    normalized = _normalize_api_mode(explicit_api_mode)
    if normalized is not None:
        return normalized

    url = (base_url or "").rstrip("/")
    if url:
        lowered = url.lower()
        hostname = urlparse(url).hostname or ""
        if lowered.endswith("/anthropic") or hostname == "api.anthropic.com":
            return "anthropic_messages"
        if hostname in {"api.openai.com", "api.x.ai"} or "/backend-api/codex" in lowered:
            return "codex_responses"

    provider_lower = (provider or "").strip().lower()
    if provider_lower in {"anthropic", "minimax", "minimax-cn"}:
        return "anthropic_messages"
    if provider_lower in {"openai-codex", "xai"}:
        return "codex_responses"

    model_lower = (model or "").strip().lower()
    if model_lower.startswith("claude-") and url.lower().endswith("/anthropic"):
        return "anthropic_messages"

    return "chat_completions"


def _ensure_default_runtime_defaults(config: dict[str, object]) -> dict[str, object]:
    resolved = dict(config)
    existing_base_instructions = resolved.get("base_instructions")
    if not (isinstance(existing_base_instructions, str) and existing_base_instructions.strip()):
        resolved["base_instructions"] = MENTE_DEFAULT_BASE_INSTRUCTIONS

    if not isinstance(resolved.get("model_auto_compact_token_limit"), int):
        resolved["model_auto_compact_token_limit"] = MENTE_DEFAULT_AUTO_COMPACT_TOKEN_LIMIT

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


def _extract_profile_overrides(
    config: dict[str, object],
) -> tuple[dict[str, object], dict[str, dict[str, object]]]:
    resolved = dict(config)
    raw_profiles = resolved.pop("profiles", None)
    if not isinstance(raw_profiles, dict):
        return resolved, {}

    normalized: dict[str, dict[str, object]] = {}
    for profile_name, profile_config in raw_profiles.items():
        if not isinstance(profile_name, str) or not isinstance(profile_config, dict):
            continue
        normalized[profile_name] = dict(profile_config)
    return resolved, normalized


def _resolve_request_profile_override(
    runtime_config: RuntimeConfig,
    request: ExecutionRequest,
) -> dict[str, object]:
    if _is_coordinator_request(request):
        coordinator_override = runtime_config.profile_overrides.get(_COORDINATOR_PROFILE, {})
        if coordinator_override:
            return dict(coordinator_override)
        return dict(runtime_config.profile_overrides.get(_DIRECTOR_LANE, {}))
    if _is_content_publishing_request(request):
        return dict(runtime_config.profile_overrides.get(_CONTENT_PUBLISHING_TASK_PROFILE, {}))
    if _is_config_admin_request(request):
        return dict(runtime_config.profile_overrides.get(_CONFIG_ADMIN_TASK_PROFILE, {}))
    if str(request.metadata.get("task_profile") or "").strip().lower() == _DEEP_RESEARCH_TASK_PROFILE:
        return dict(runtime_config.profile_overrides.get(_DEEP_RESEARCH_TASK_PROFILE, {}))
    request_lane = _resolved_request_lane(request)
    if request_lane in {
        _DIRECTOR_LANE,
        _ENGINEERING_LANE,
        _RESEARCH_LANE,
        _WRITING_LANE,
        _CONFIG_ADMIN_LANE,
    }:
        return dict(runtime_config.profile_overrides.get(request_lane, {}))
    return {}


def _deep_merge_config(
    base: dict[str, object],
    overlay: dict[str, object],
) -> dict[str, object]:
    merged = dict(base)
    for key, value in overlay.items():
        existing = merged.get(key)
        if isinstance(existing, dict) and isinstance(value, dict):
            merged[key] = _deep_merge_config(existing, value)
        else:
            merged[key] = value
    return merged


def _is_content_publishing_request(request: ExecutionRequest) -> bool:
    task_profile = str(request.metadata.get("task_profile") or "").strip()
    if task_profile == _CONTENT_PUBLISHING_TASK_PROFILE:
        return True
    return _WECHAT_PUBLISHER_SKILL_REF in {
        str(item).strip() for item in (request.skill_refs or []) if str(item).strip()
    }


def _is_config_admin_request(request: ExecutionRequest) -> bool:
    task_profile = str(request.metadata.get("task_profile") or "").strip()
    if task_profile == _CONFIG_ADMIN_TASK_PROFILE:
        return True
    if _resolved_request_lane(request) == _CONFIG_ADMIN_LANE:
        return True
    return _MENTE_CONFIG_ADMIN_SKILL_REF in {
        str(item).strip() for item in (request.skill_refs or []) if str(item).strip()
    }


def _is_coordinator_request(request: ExecutionRequest) -> bool:
    role = str(getattr(request, "role", "") or "").strip().lower()
    if role == _COORDINATOR_PROFILE:
        return True
    return _request_lane(request) in {_COORDINATOR_PROFILE, _DIRECTOR_LANE}


def _request_lane(request: ExecutionRequest) -> str:
    metadata = request.metadata if isinstance(request.metadata, dict) else {}
    lane = metadata.get("lane")
    if not isinstance(lane, str):
        return ""
    return lane.strip().lower()


def _resolved_request_lane(request: ExecutionRequest) -> str | None:
    lane = _request_lane(request)
    if lane in {
        _COORDINATOR_PROFILE,
        _DIRECTOR_LANE,
        _ENGINEERING_LANE,
        _RESEARCH_LANE,
        _WRITING_LANE,
        _CONFIG_ADMIN_LANE,
    }:
        if lane == _COORDINATOR_PROFILE:
            return _DIRECTOR_LANE
        return lane
    worker_lane = str(getattr(request, "worker_lane", "") or "").strip().lower()
    if worker_lane in {
        _DIRECTOR_LANE,
        _ENGINEERING_LANE,
        _RESEARCH_LANE,
        _WRITING_LANE,
        _CONFIG_ADMIN_LANE,
    }:
        return worker_lane
    task_profile = str(request.metadata.get("task_profile") or "").strip().lower()
    if task_profile == _DEEP_RESEARCH_TASK_PROFILE:
        return _RESEARCH_LANE
    if task_profile == _CONTENT_PUBLISHING_TASK_PROFILE:
        return _WRITING_LANE
    if task_profile == _CONFIG_ADMIN_TASK_PROFILE:
        return _CONFIG_ADMIN_LANE
    return None


def _format_config_override(key: str, value: object) -> str:
    return f"{key}={json.dumps(value, ensure_ascii=True)}"
