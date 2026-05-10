"""Mente-owned host-side MCP bridge overlays for private Codex runtimes."""

from __future__ import annotations

from collections.abc import Mapping
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from typing import Any, Callable
from urllib.parse import urlparse

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
_WECHAT_WHITELIST_FAILURE_SUMMARY = (
    "微信公众号接口拒绝访问：当前服务器 IP 未加入白名单。"
    "文章与配图已生成，请在微信公众平台后台将该服务器 IP 加入白名单后重试。"
)
_WECHAT_WHITELIST_ERROR_RE = re.compile(
    r"(invalid ip\s+[^\n,]+(?:,\s*ipv6\s+[^\n,]+)?\s*,\s*not in whitelist)",
    re.IGNORECASE,
)
_MARKDOWN_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
_FRONTMATTER_COVER_RE = re.compile(r"(?mi)^cover:\s*(.+)$")
_WECHAT_CONFIG_KEYS = ("WECHAT_APP_ID", "WECHAT_APP_SECRET")
_LOCAL_IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp")


def model_visible_mcp_tool_name(server_name: str, tool_name: str) -> str:
    """Return the Codex model-visible callable name for an MCP bridge tool."""

    normalized_server = str(server_name).strip()
    normalized_tool = str(tool_name).strip()
    if not normalized_server or not normalized_tool:
        return normalized_tool
    return f"mcp__{normalized_server}__{normalized_tool}"


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
    wechat_access_token_loader: Callable[..., str] | None = None,
    wechat_image_uploader: Callable[[Path, str], str] | None = None,
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
    env = dict(os.environ)
    env["HOME"] = os.environ.get("MENTE_HOST_HOME", env.get("HOME", str(Path.home())))
    _ensure_wenyan_cache_dir(Path(env["HOME"]))
    publish_mode = "article_markdown"
    publish_script = resolved_skill_root / "scripts" / "publisher" / "publish.js"
    create_article_script = resolved_skill_root / "scripts" / "publisher" / "create-article.js"
    prepared_article_path = resolved_article_path
    prepared_temp_path: Path | None = None
    if _looks_like_source_markdown(resolved_article_path):
        if not create_article_script.is_file():
            return {
                "ok": False,
                "error": "create_article_script_not_found",
                "article_path": str(resolved_article_path),
                "source_path": str(resolved_article_path),
                "create_article_script": str(create_article_script),
            }
        publish_mode = "source_markdown"
        command = [
            "node",
            str(create_article_script),
            _resolve_markdown_title(resolved_article_path),
            "--from",
            str(resolved_article_path),
            "--publish",
        ]
        if sync:
            command.extend(["--sync", sync])
    else:
        if not publish_script.is_file():
            return {
                "ok": False,
                "error": "publish_script_not_found",
                "article_path": str(resolved_article_path),
                "publish_script": str(publish_script),
            }
        try:
            prepared_article_path, prepared_temp_path = _prepare_article_markdown_for_publish(
                resolved_article_path,
                skill_root=resolved_skill_root,
                access_token_loader=wechat_access_token_loader or _load_wechat_access_token_for_publish,
                image_uploader=wechat_image_uploader or _upload_wechat_image_for_publish,
            )
        except Exception as exc:
            return {
                "ok": False,
                "error": "wechat_publish_prepare_failed",
                "failure_summary": f"公众号草稿发布前处理图片失败：{exc}",
                "article_path": str(resolved_article_path),
                "publish_script": str(publish_script),
            }
        command = [
            "node",
            str(publish_script),
            str(prepared_article_path),
            theme,
            highlight,
        ]
        if sync:
            command.extend(["--sync", sync])

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
        if prepared_temp_path is not None:
            prepared_temp_path.unlink(missing_ok=True)
        result = {
            "ok": False,
            "error": f"spawn_error:{type(exc).__name__}:{exc}",
            "article_path": str(resolved_article_path),
            "command": command,
        }
        if publish_mode == "source_markdown":
            result["source_path"] = str(resolved_article_path)
            result["create_article_script"] = str(create_article_script)
        else:
            result["publish_script"] = str(publish_script)
        return result

    result = {
        "ok": completed.returncode == 0,
        "article_path": str(resolved_article_path),
        "finalize_mode": publish_mode,
        "command": command,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "returncode": completed.returncode,
    }
    if publish_mode == "source_markdown":
        result["source_path"] = str(resolved_article_path)
        result["create_article_script"] = str(create_article_script)
    else:
        result["publish_script"] = str(publish_script)
    if completed.returncode != 0:
        classified_failure = _classify_publish_failure(
            stdout=completed.stdout,
            stderr=completed.stderr,
            returncode=completed.returncode,
        )
        result.update(classified_failure)
    if prepared_temp_path is not None:
        prepared_temp_path.unlink(missing_ok=True)
    return result


def _classify_publish_failure(
    *,
    stdout: str,
    stderr: str,
    returncode: int,
) -> dict[str, object]:
    combined = "\n".join(part for part in (stderr, stdout) if part).strip()
    whitelist_match = _WECHAT_WHITELIST_ERROR_RE.search(combined)
    if whitelist_match:
        return {
            "error": "wechat_ip_not_whitelisted",
            "failure_summary": _WECHAT_WHITELIST_FAILURE_SUMMARY,
            "error_detail": whitelist_match.group(1),
        }
    return {
        "error": f"exit_code:{returncode}",
    }


def _prepare_article_markdown_for_publish(
    article_path: Path,
    *,
    skill_root: Path,
    access_token_loader: Callable[..., str],
    image_uploader: Callable[[Path, str], str],
) -> tuple[Path, Path | None]:
    markdown = article_path.read_text(encoding="utf-8")
    prepared_markdown = _normalize_frontmatter_cover_reference(markdown, article_path.parent)
    local_images = _collect_local_markdown_images(prepared_markdown, article_path.parent)
    if local_images:
        access_token = access_token_loader(skill_root=skill_root)
        upload_cache: dict[str, str] = {}
        for image in local_images:
            cache_key = image["original_ref"]
            if cache_key in upload_cache:
                continue
            upload_cache[cache_key] = image_uploader(image["resolved_path"], access_token)
        prepared_markdown = _replace_markdown_image_references(prepared_markdown, upload_cache)
    if prepared_markdown == markdown:
        return article_path, None
    temp_path = _write_prepared_publish_markdown(article_path, prepared_markdown)
    return temp_path, temp_path


def _normalize_frontmatter_cover_reference(markdown: str, article_dir: Path) -> str:
    def _replace(match: re.Match[str]) -> str:
        raw_ref = match.group(1).strip().strip("\"'")
        if not _looks_like_local_path(raw_ref):
            return match.group(0)
        resolved = _resolve_local_asset_reference(article_dir, raw_ref)
        if resolved is None:
            return match.group(0)
        normalized_ref, _ = resolved
        if normalized_ref == raw_ref:
            return match.group(0)
        return f"cover: {normalized_ref}"

    return _FRONTMATTER_COVER_RE.sub(_replace, markdown, count=1)


def _collect_local_markdown_images(markdown: str, article_dir: Path) -> list[dict[str, object]]:
    collected: list[dict[str, object]] = []
    for match in _MARKDOWN_IMAGE_RE.finditer(markdown):
        image_ref = match.group(2).strip()
        if not _looks_like_local_path(image_ref):
            continue
        resolved = _resolve_local_asset_reference(article_dir, image_ref)
        if resolved is None:
            continue
        normalized_ref, resolved_path = resolved
        collected.append(
            {
                "original_ref": image_ref,
                "normalized_ref": normalized_ref,
                "resolved_path": resolved_path,
            }
        )
    return collected


def _replace_markdown_image_references(markdown: str, replacements: Mapping[str, str]) -> str:
    def _replace(match: re.Match[str]) -> str:
        alt_text = match.group(1)
        image_ref = match.group(2).strip()
        replacement = replacements.get(image_ref)
        if replacement is None:
            return match.group(0)
        return f"![{alt_text}]({replacement})"

    return _MARKDOWN_IMAGE_RE.sub(_replace, markdown)


def _resolve_local_asset_reference(article_dir: Path, raw_ref: str) -> tuple[str, Path] | None:
    reference_path = Path(raw_ref)
    candidate = (article_dir / reference_path).resolve()
    if candidate.is_file():
        return raw_ref, candidate
    if reference_path.suffix:
        for extension in _LOCAL_IMAGE_EXTENSIONS:
            sibling = candidate.with_suffix(extension)
            if sibling.is_file():
                normalized_ref = _render_relative_asset_reference(
                    article_dir,
                    sibling,
                    original_ref=raw_ref,
                )
                return normalized_ref, sibling
    return None


def _render_relative_asset_reference(article_dir: Path, asset_path: Path, *, original_ref: str) -> str:
    relative_path = os.path.relpath(asset_path, article_dir).replace(os.sep, "/")
    if original_ref.startswith("./"):
        return f"./{relative_path}"
    return relative_path


def _looks_like_local_path(value: str) -> bool:
    if not value:
        return False
    lowered = value.lower()
    if lowered.startswith("data:"):
        return False
    parsed = urlparse(value)
    return not parsed.scheme


def _write_prepared_publish_markdown(article_path: Path, markdown: str) -> Path:
    temp_dir = article_path.parent
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        suffix=article_path.suffix,
        prefix=f".{article_path.stem}.mente-publish.",
        dir=temp_dir,
        delete=False,
    ) as handle:
        handle.write(markdown)
        return Path(handle.name)


def _load_wechat_access_token_for_publish(*, skill_root: Path) -> str:
    credentials = _load_wechat_credentials(skill_root)
    if not credentials["app_id"] or not credentials["app_secret"]:
        raise RuntimeError("未找到微信公众号凭证")
    try:
        import requests
    except ImportError as exc:
        raise RuntimeError("缺少 requests 依赖，无法上传公众号图片") from exc
    response = requests.get(
        "https://api.weixin.qq.com/cgi-bin/token",
        params={
            "grant_type": "client_credential",
            "appid": credentials["app_id"],
            "secret": credentials["app_secret"],
        },
        timeout=30,
    )
    response.raise_for_status()
    payload = _load_json_response_text(response.text)
    access_token = str(payload.get("access_token") or "").strip()
    if access_token:
        return access_token
    raise RuntimeError(str(payload.get("errmsg") or "获取微信公众号 access_token 失败"))


def _upload_wechat_image_for_publish(image_path: Path, access_token: str) -> str:
    try:
        import requests
    except ImportError as exc:
        raise RuntimeError("缺少 requests 依赖，无法上传公众号图片") from exc
    mime_type = "image/png" if image_path.suffix.lower() == ".png" else "image/jpeg"
    with image_path.open("rb") as handle:
        response = requests.post(
            f"https://api.weixin.qq.com/cgi-bin/media/uploadimg?access_token={access_token}",
            files={"media": (image_path.name, handle, mime_type)},
            timeout=60,
        )
    response.raise_for_status()
    payload = _load_json_response_text(response.text)
    image_url = str(payload.get("url") or "").strip()
    if image_url:
        return image_url
    raise RuntimeError(str(payload.get("errmsg") or "上传公众号图片失败"))


def _load_wechat_credentials(skill_root: Path) -> dict[str, str]:
    env_app_id = str(os.environ.get("WECHAT_APP_ID") or "").strip()
    env_app_secret = str(os.environ.get("WECHAT_APP_SECRET") or "").strip()
    if env_app_id and env_app_secret:
        return {
            "app_id": env_app_id,
            "app_secret": env_app_secret,
        }
    config_paths = (
        skill_root / ".wechat.config",
        Path.home() / ".wechat.config",
    )
    for config_path in config_paths:
        if not config_path.is_file():
            continue
        parsed = _parse_simple_env_file(config_path)
        app_id = parsed.get("WECHAT_APP_ID", "").strip()
        app_secret = parsed.get("WECHAT_APP_SECRET", "").strip()
        if app_id and app_secret:
            return {
                "app_id": app_id,
                "app_secret": app_secret,
            }
    return {
        "app_id": "",
        "app_secret": "",
    }


def _parse_simple_env_file(path: Path) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        match = re.match(r"^(?:export\s+)?([A-Z0-9_]+)=(.*)$", line)
        if not match:
            continue
        key = match.group(1)
        value = match.group(2).strip()
        if (
            len(value) >= 2
            and ((value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")))
        ):
            value = value[1:-1]
        parsed[key] = value
    return parsed


def _load_json_response_text(raw_text: str) -> dict[str, object]:
    try:
        loaded = json.loads(raw_text or "{}")
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"微信公众号接口返回了非 JSON 内容: {exc}") from exc
    if not isinstance(loaded, dict):
        raise RuntimeError("微信公众号接口返回了非对象响应")
    return loaded


def _ensure_wenyan_cache_dir(host_home: Path) -> None:
    (host_home / ".config" / "wenyan-md").mkdir(parents=True, exist_ok=True)


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


def _looks_like_source_markdown(path: Path) -> bool:
    return path.suffix.lower() == ".md" and path.name.lower() == "source.md"


def _resolve_markdown_title(path: Path) -> str:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return path.parent.name or path.stem

    in_frontmatter = bool(lines and lines[0].strip() == "---")
    if in_frontmatter:
        for line in lines[1:64]:
            stripped = line.strip()
            if stripped == "---":
                break
            if stripped.lower().startswith("title:"):
                title = stripped.partition(":")[2].strip().strip("\"'")
                if title:
                    return title
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("# "):
            heading = stripped[2:].strip()
            if heading:
                return heading
    return path.parent.name or path.stem


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
