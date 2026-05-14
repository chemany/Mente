"""Launcher helpers for the vendored Codex kernel slice."""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

from hermes_constants import get_mente_home
from kernel.codex.runtime.protocol import KernelExecutionPayload
from kernel.codex.session.protocol import KernelSessionMode, KernelSessionRequest

if TYPE_CHECKING:
    from mente.executors.runtime_config import RuntimeConfig


def build_exec_command(
    *,
    codex_binary: str,
    payload: KernelExecutionPayload,
    session: KernelSessionRequest,
    sandbox: str,
    approval_policy: str,
    runtime_config: RuntimeConfig,
    output_last_message: str | None = None,
    output_schema: str | None = None,
    workdir: str | None = None,
    add_dirs: list[str] | None = None,
) -> list[str]:
    """Build the Codex CLI command for one vendored exec invocation."""
    command = [
        codex_binary,
        "exec",
    ]
    if session.mode is KernelSessionMode.STATELESS:
        command.append("--ephemeral")
    if runtime_config.ignore_user_config:
        command.append("--ignore-user-config")
    if runtime_config.ignore_rules:
        command.append("--ignore-rules")
    for override in _build_execution_mode_overrides(
        sandbox=sandbox,
        runtime_config=runtime_config,
    ):
        command.extend(["-c", override])
    for override in runtime_config.to_codex_overrides():
        command.extend(["-c", override])
    # Mente owns the canonical skills root via MENTE_SKILLS_DIR. Disable Codex's
    # embedded system-skill cache so no private CODEX_HOME/skills tree is created.
    command.extend(["-c", "skills.bundled.enabled=false"])
    command.extend(_build_execution_mode_args(sandbox=sandbox, approval_policy=approval_policy))
    if runtime_config.skip_git_repo_check is not False:
        command.append("--skip-git-repo-check")
    command.extend(
        [
            "--color",
            _resolve_color(runtime_config),
            "--cd",
            workdir or payload.workspace,
        ]
    )
    for add_dir in add_dirs or []:
        command.extend(["--add-dir", add_dir])
    if output_last_message:
        command.extend(["--output-last-message", output_last_message])
    if output_schema:
        command.extend(["--output-schema", output_schema])
    if session.mode is KernelSessionMode.SESSION and session.session_id:
        command.extend(["resume", session.session_id])
    command.append(payload.prompt)
    return command


def build_stateless_command(
    *,
    codex_binary: str,
    payload: KernelExecutionPayload,
    session: KernelSessionRequest,
    sandbox: str,
    approval_policy: str,
    runtime_config: RuntimeConfig,
    output_last_message: str | None = None,
    output_schema: str | None = None,
    workdir: str | None = None,
    add_dirs: list[str] | None = None,
) -> list[str]:
    """Build the Codex CLI command for the vendored stateless transport path."""
    if session.mode is not KernelSessionMode.STATELESS:
        msg = "C1 launcher only supports stateless execution"
        raise ValueError(msg)
    return build_exec_command(
        codex_binary=codex_binary,
        payload=payload,
        session=session,
        sandbox=sandbox,
        approval_policy=approval_policy,
        runtime_config=runtime_config,
        output_last_message=output_last_message,
        output_schema=output_schema,
        workdir=workdir,
        add_dirs=add_dirs,
    )


def build_private_runtime_env(
    codex_home: Path,
    extra_env: dict[str, str] | None = None,
) -> dict[str, str]:
    """Construct the isolated subprocess environment for a private runtime home."""
    env: dict[str, str] = {}
    for key in (
        "LANG",
        "LC_ALL",
        "OPENAI_API_KEY",
        "OPENAI_BASE_URL",
        "OPENAI_ORGANIZATION",
        "OPENAI_PROJECT",
        "PATH",
        "PYTHONIOENCODING",
        "PYTHONPATH",
        "SHELL",
        "SSL_CERT_DIR",
        "SSL_CERT_FILE",
        "SYSTEMROOT",
        "TERM",
        "TMP",
        "TEMP",
        "TMPDIR",
    ):
        value = os.environ.get(key)
        if value:
            env[key] = value
    if (
        extra_env
        and extra_env.get("MENTE_CODEX_API_KEY")
        and "OPENAI_API_KEY" not in extra_env
    ):
        # The private Mente runtime resolves auth through MENTE_CODEX_API_KEY.
        # Do not leak an ambient public OPENAI_API_KEY into nested child flows,
        # or legacy Hermes/OpenRouter fallbacks may pick it up and misroute.
        env.pop("OPENAI_API_KEY", None)
    for key, value in (extra_env or {}).items():
        if value:
            env[key] = value
    runtime_path_dir = codex_home / "path"
    if runtime_path_dir.is_dir():
        existing_path = env.get("PATH", "")
        path_sep = ";" if os.name == "nt" else ":"
        env["PATH"] = str(runtime_path_dir) + (
            path_sep + existing_path if existing_path else ""
        )
    canonical_mente_home = str(get_mente_home())
    env["HOME"] = str(codex_home)
    env["CODEX_HOME"] = str(codex_home)
    env["MENTE_HOME"] = canonical_mente_home
    env["HERMES_HOME"] = canonical_mente_home
    env["MENTE_SKILLS_DIR"] = str(get_mente_home() / "skills")
    return env


def _build_execution_mode_args(*, sandbox: str, approval_policy: str) -> list[str]:
    if approval_policy == "never":
        if sandbox == "danger-full-access":
            return ["--dangerously-bypass-approvals-and-sandbox"]
        return ["--sandbox", sandbox, "--full-auto"]
    return ["--sandbox", sandbox]


def _build_execution_mode_overrides(
    *,
    sandbox: str,
    runtime_config: RuntimeConfig,
) -> list[str]:
    if (
        sandbox == "workspace-write"
        and not _has_explicit_workspace_network_override(runtime_config.codex_config)
    ):
        return ["sandbox_workspace_write.network_access=true"]
    return []


def _has_explicit_workspace_network_override(config: dict[str, object]) -> bool:
    sandbox_workspace_write = config.get("sandbox_workspace_write")
    if not isinstance(sandbox_workspace_write, dict):
        return False
    return "network_access" in sandbox_workspace_write


def _resolve_color(runtime_config: RuntimeConfig) -> str:
    configured = runtime_config.color
    if isinstance(configured, str) and configured.strip():
        return configured.strip()
    return "never"
