"""Stateless launcher helpers for the vendored Codex kernel slice."""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

from kernel.codex.runtime.protocol import KernelExecutionPayload
from kernel.codex.session.protocol import KernelSessionMode, KernelSessionRequest

if TYPE_CHECKING:
    from mente.executors.runtime_config import RuntimeConfig


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

    command = [
        codex_binary,
        "exec",
        "--ephemeral",
    ]
    if runtime_config.ignore_user_config:
        command.append("--ignore-user-config")
    if runtime_config.ignore_rules:
        command.append("--ignore-rules")
    for override in runtime_config.to_codex_overrides():
        command.extend(["-c", override])
    command.extend(_build_execution_mode_args(sandbox=sandbox, approval_policy=approval_policy))
    command.extend(
        [
            "--skip-git-repo-check",
            "--color",
            "never",
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
    command.append(payload.prompt)
    return command


def build_private_runtime_env(codex_home: Path) -> dict[str, str]:
    """Construct the isolated subprocess environment for a private runtime home."""
    env: dict[str, str] = {}
    for key in (
        "LANG",
        "LC_ALL",
        "OPENAI_API_KEY",
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
    env["HOME"] = str(codex_home)
    env["CODEX_HOME"] = str(codex_home)
    return env


def _build_execution_mode_args(*, sandbox: str, approval_policy: str) -> list[str]:
    if approval_policy == "never":
        if sandbox == "danger-full-access":
            return ["--dangerously-bypass-approvals-and-sandbox"]
        return ["--sandbox", sandbox, "--full-auto"]
    return ["--sandbox", sandbox]
