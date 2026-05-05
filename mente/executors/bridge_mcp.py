"""Mente-owned host-side MCP bridge overlays for private Codex runtimes."""

from __future__ import annotations

from collections.abc import Mapping
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any, Callable

from hermes_constants import get_mente_home, get_skills_dir

from mente.executors.runtime_config import RuntimeConfig
from mente.feature_flags import (
    filter_enabled_bridge_tools,
    is_memory_read_tool_enabled,
    is_memory_write_tool_enabled,
)
from mente.memory.context import persist_explicit_memory_write, resolve_explicit_memory_read
from mente.memory.policy import MemoryPolicyResolver
from mente.memory.repository import MemoryRepository, SQLiteMemoryRepository
from mente.task_core.models import ExecutionRequest, Task


_SUPPORTED_MCP_BRIDGE_TOOLS = (
    "mente_memory_query",
    "mente_memory_save",
    "mente_wechat_publish_draft",
)
_LEGACY_BRIDGE_TOOL_ALIASES = {
    "mente_memory_append": "mente_memory_save",
}
_MCP_SERVER_NAME = "mente"
_MCP_SERVER_MODULE = "mente.executors.mcp_server"
_DEFAULT_THEME = "lapis"
_DEFAULT_HIGHLIGHT = "solarized-light"
_TOOL_POLICY_ENV = "MENTE_TOOL_POLICY_JSON"
_EXECUTION_CONTEXT_ENV = "MENTE_EXECUTION_CONTEXT_JSON"
_EXPLICIT_MEMORY_WRITE_ORIGIN = "explicit_memory_write"
_EXPLICIT_MEMORY_WRITE_TOOL = "mente_memory_save"


def augment_runtime_config_for_bridge_tools(
    runtime_config: RuntimeConfig,
    request: ExecutionRequest,
) -> RuntimeConfig:
    """Inject Mente-owned MCP servers only for supported bridge tools."""

    requested_tools = _requested_mcp_bridge_tools(request)
    if not requested_tools:
        return runtime_config

    repo_root = Path(__file__).resolve().parents[2]
    codex_config = _deep_merge(
        dict(runtime_config.codex_config),
        {
            "mcp_servers": {
                _MCP_SERVER_NAME: {
                    "command": _resolve_mcp_python_command(repo_root),
                    "args": ["-m", _MCP_SERVER_MODULE],
                    "cwd": str(repo_root),
                    "default_tools_approval_mode": "approve",
                    "enabled_tools": requested_tools,
                }
            }
        },
    )
    subprocess_env = dict(runtime_config.subprocess_env)
    subprocess_env.setdefault("MENTE_HOME", str(get_mente_home()))
    subprocess_env.setdefault(
        "MENTE_HOST_HOME",
        os.environ.get("MENTE_HOST_HOME", str(Path.home())),
    )
    tool_policy = request.tool_policy if isinstance(request.tool_policy, dict) else {}
    subprocess_env.setdefault(
        _TOOL_POLICY_ENV,
        json.dumps(tool_policy, sort_keys=True, separators=(",", ":")),
    )
    subprocess_env.setdefault(
        _EXECUTION_CONTEXT_ENV,
        json.dumps(
            {
                "task_id": request.task_id,
                "session_id": request.session_id,
                "task_type": request.task_type,
                "source": tool_policy.get("source") or request.metadata.get("source"),
                "policy_id": tool_policy.get("policy_id"),
            },
            sort_keys=True,
            separators=(",", ":"),
        ),
    )
    return RuntimeConfig(
        runtime_home=runtime_config.runtime_home,
        ignore_user_config=runtime_config.ignore_user_config,
        ignore_rules=runtime_config.ignore_rules,
        codex_config=codex_config,
        subprocess_env=subprocess_env,
    )


def publish_wechat_draft(
    *,
    article_path: str,
    theme: str = _DEFAULT_THEME,
    highlight: str = _DEFAULT_HIGHLIGHT,
    sync: str | None = None,
    skill_root: Path | None = None,
    subprocess_run: Callable[..., Any] = subprocess.run,
) -> dict[str, object]:
    """Publish a local markdown article through the host WeChat workflow."""

    resolved_article_path = Path(article_path).expanduser()
    if not resolved_article_path.is_file():
        return {
            "ok": False,
            "error": "article_not_found",
            "article_path": str(resolved_article_path),
        }

    resolved_skill_root = skill_root or (get_skills_dir() / "media" / "wechat-publisher")
    publish_script = resolved_skill_root / "scripts" / "publisher" / "publish.js"
    if not publish_script.is_file():
        return {
            "ok": False,
            "error": "publish_script_not_found",
            "article_path": str(resolved_article_path),
            "publish_script": str(publish_script),
        }

    command = [
        "node",
        str(publish_script),
        str(resolved_article_path),
        theme,
        highlight,
    ]
    if sync:
        command.extend(["--sync", sync])

    env = dict(os.environ)
    env["HOME"] = os.environ.get("MENTE_HOST_HOME", env.get("HOME", str(Path.home())))
    try:
        completed = subprocess_run(
            command,
            capture_output=True,
            text=True,
            check=False,
            cwd=str(resolved_skill_root),
            env=env,
        )
    except OSError as exc:
        return {
            "ok": False,
            "error": f"spawn_error:{type(exc).__name__}:{exc}",
            "article_path": str(resolved_article_path),
            "publish_script": str(publish_script),
            "command": command,
        }

    result = {
        "ok": completed.returncode == 0,
        "article_path": str(resolved_article_path),
        "publish_script": str(publish_script),
        "command": command,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "returncode": completed.returncode,
    }
    if completed.returncode != 0:
        result["error"] = f"exit_code:{completed.returncode}"
    return result


def query_mente_memory(
    *,
    memory_scope: str | None = None,
    limit: int | None = None,
    repository: MemoryRepository | None = None,
    memory_policy_resolver: MemoryPolicyResolver | None = None,
    environment: Mapping[str, str] | None = None,
) -> dict[str, object]:
    """Query Mente-owned memory through a policy-bounded execution bridge."""

    env = environment or os.environ
    execution_context = _load_json_object(env.get(_EXECUTION_CONTEXT_ENV))
    tool_policy = _load_json_object(env.get(_TOOL_POLICY_ENV))
    policy_id = str(execution_context.get("policy_id") or tool_policy.get("policy_id") or "")
    if not is_memory_read_tool_enabled(environment=env):
        return _deny_memory_read(policy_id=policy_id, reason="disabled")
    if not execution_context:
        return _deny_memory_read(policy_id=policy_id, reason="missing_execution_context")
    if "mente_memory_query" not in _bridge_tools_from_policy(tool_policy):
        return _deny_memory_read(policy_id=policy_id, reason="tool_not_enabled")

    task = _build_execution_context_task(execution_context)
    if task is None:
        return _deny_memory_read(policy_id=policy_id, reason="invalid_execution_context")

    policy_resolver = memory_policy_resolver or MemoryPolicyResolver.default()
    resolved_policy = policy_resolver.resolve(task)
    effective_repository = repository or SQLiteMemoryRepository()
    try:
        records, denial_reason = resolve_explicit_memory_read(
            task,
            memory_repository=effective_repository,
            requested_scope=memory_scope,
            requested_limit=limit,
            memory_policy_resolver=policy_resolver,
        )
    finally:
        if repository is None:
            try:
                effective_repository.close()
            except Exception:
                pass
    if denial_reason is not None:
        return _deny_memory_read(
            policy_id=resolved_policy.policy_id,
            reason=denial_reason,
        )
    return {
        "ok": True,
        "policy_id": resolved_policy.policy_id,
        "results": [
            {
                "memory_id": record.memory_id,
                "task_id": record.task_id,
                "scope": record.scope,
                "fact": record.fact,
                "source": record.source,
                "task_type": record.task_type,
            }
            for record in records
        ],
    }


def save_mente_memory(
    *,
    fact: str,
    memory_scope: str | None = None,
    repository: MemoryRepository | None = None,
    memory_policy_resolver: MemoryPolicyResolver | None = None,
    environment: Mapping[str, str] | None = None,
) -> dict[str, object]:
    """Persist Mente-owned memory through a policy-bounded execution bridge."""

    env = environment or os.environ
    execution_context = _load_json_object(env.get(_EXECUTION_CONTEXT_ENV))
    tool_policy = _load_json_object(env.get(_TOOL_POLICY_ENV))
    policy_id = str(execution_context.get("policy_id") or tool_policy.get("policy_id") or "")
    if not is_memory_write_tool_enabled(environment=env):
        return _deny_memory_write(policy_id=policy_id, reason="disabled")
    if not execution_context:
        return _deny_memory_write(policy_id=policy_id, reason="missing_execution_context")
    if _EXPLICIT_MEMORY_WRITE_TOOL not in _bridge_tools_from_policy(tool_policy):
        return _deny_memory_write(policy_id=policy_id, reason="tool_not_enabled")

    task = _build_execution_context_task(execution_context)
    if task is None:
        return _deny_memory_write(policy_id=policy_id, reason="invalid_execution_context")

    policy_resolver = memory_policy_resolver or MemoryPolicyResolver.default()
    resolved_policy = policy_resolver.resolve(task)
    effective_repository = repository or SQLiteMemoryRepository()
    try:
        record, denial_reason = persist_explicit_memory_write(
            task,
            fact=fact,
            requested_scope=memory_scope,
            memory_repository=effective_repository,
            memory_policy_resolver=policy_resolver,
            tool_name=_EXPLICIT_MEMORY_WRITE_TOOL,
            write_origin=_EXPLICIT_MEMORY_WRITE_ORIGIN,
        )
    finally:
        if repository is None:
            try:
                effective_repository.close()
            except Exception:
                pass
    if denial_reason is not None or record is None:
        return _deny_memory_write(
            policy_id=resolved_policy.policy_id,
            reason=denial_reason or "memory_write_failed",
        )
    return {
        "ok": True,
        "policy_id": resolved_policy.policy_id,
        "memory_id": record.memory_id,
        "scope": record.scope,
        "fact": record.fact,
        "metadata": dict(record.metadata),
    }


def _requested_mcp_bridge_tools(request: ExecutionRequest) -> list[str]:
    tool_policy = request.tool_policy if isinstance(request.tool_policy, dict) else {}
    bridge_tools = _normalize_bridge_tools(tool_policy.get("bridge_tools", []))
    if not isinstance(bridge_tools, list):
        return []
    enabled_bridge_tools = set(filter_enabled_bridge_tools(bridge_tools))
    return [name for name in _SUPPORTED_MCP_BRIDGE_TOOLS if name in enabled_bridge_tools]


def _bridge_tools_from_policy(tool_policy: Mapping[str, object]) -> list[str]:
    bridge_tools = _normalize_bridge_tools(tool_policy.get("bridge_tools", []))
    if not isinstance(bridge_tools, list):
        return []
    return [str(name) for name in bridge_tools]


def _normalize_bridge_tools(raw_bridge_tools: object) -> list[str] | object:
    if not isinstance(raw_bridge_tools, list):
        return raw_bridge_tools

    normalized: list[str] = []
    for name in raw_bridge_tools:
        normalized_name = _LEGACY_BRIDGE_TOOL_ALIASES.get(str(name), str(name))
        if normalized_name not in normalized:
            normalized.append(normalized_name)
    return normalized


def _load_json_object(raw_value: str | None) -> dict[str, object]:
    if not raw_value:
        return {}
    try:
        loaded = json.loads(raw_value)
    except json.JSONDecodeError:
        return {}
    if not isinstance(loaded, dict):
        return {}
    return loaded


def _build_execution_context_task(execution_context: Mapping[str, object]) -> Task | None:
    task_id = str(execution_context.get("task_id") or "").strip()
    session_id = str(execution_context.get("session_id") or "").strip()
    task_type = str(execution_context.get("task_type") or "").strip()
    source = str(execution_context.get("source") or "").strip()
    if not task_id or not session_id or not task_type or not source:
        return None
    return Task(
        task_id=task_id,
        session_id=session_id,
        task_type=task_type,
        objective="Mente bridge memory query",
        user_request="Read Mente memory through the execution bridge.",
        metadata={"source": source},
    )


def _deny_memory_read(*, policy_id: str | None, reason: str) -> dict[str, object]:
    return {
        "ok": False,
        "error": "memory_read_not_allowed",
        "policy_id": policy_id or None,
        "reason": reason,
    }


def _deny_memory_write(*, policy_id: str | None, reason: str) -> dict[str, object]:
    return {
        "ok": False,
        "error": "memory_write_not_allowed",
        "policy_id": policy_id or None,
        "reason": reason,
    }


def _resolve_mcp_python_command(repo_root: Path) -> str:
    for candidate in (
        repo_root / ".venv" / "bin" / "python",
        repo_root / "venv" / "bin" / "python",
    ):
        if candidate.is_file():
            return str(candidate)
    return sys.executable


def _deep_merge(base: dict[str, object], overlay: dict[str, object]) -> dict[str, object]:
    merged = dict(base)
    for key, value in overlay.items():
        existing = merged.get(key)
        if isinstance(existing, dict) and isinstance(value, dict):
            merged[key] = _deep_merge(existing, value)
        else:
            merged[key] = value
    return merged
