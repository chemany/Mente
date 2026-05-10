"""Import-safe bridge metadata and call helpers for vendored Codex entry selection.

Phase C4 keeps the upper-layer seam at ``CodexKernelAdapter`` while moving the
execution control plane away from the ambient user ``codex`` binary and toward a
Mente-owned vendored front door selected by the bridge.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
import logging
import os
from pathlib import Path
import signal
import subprocess
import threading
import time
from typing import TYPE_CHECKING, Any

from kernel.codex.release.runtime import (
    RuntimeNotBootstrappedError,
    expected_vendored_runtime_binary_path,
    resolve_vendored_runtime_binary,
)
from kernel.codex.runtime.launcher import build_exec_command, build_private_runtime_env
from kernel.codex.session.protocol import KernelSessionMode, KernelSessionRequest

if TYPE_CHECKING:
    from kernel.codex.runtime.protocol import KernelExecutionPayload
    from mente.executors.runtime_config import RuntimeConfig


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CodexSnapshotBridgeSurface:
    """Metadata-only description of the vendored Codex bootstrap contract."""

    upstream_root: Path
    bridge_root: Path
    patch_root: Path
    rust_cli_entrypoint: Path
    rust_exec_entrypoint: Path
    python_sdk_root: Path
    app_server_root: Path
    runtime_locator_module: Path
    runtime_binary_path: Path
    adapter_seam: str = "CodexKernelAdapter"
    selected_front_door: str = "vendored_runtime_binary"
    bootstrap_owner: str = "kernel.codex.bridge"
    runtime_locator_policy: str = "mente_release_freeze_manifest"
    requires_sys_path_injection: bool = False
    uses_ambient_codex_discovery: bool = False
    uses_public_codex_binary: bool = False
    cutover_complete: bool = False
    execution_path_switched: bool = False


@dataclass(frozen=True)
class CodexBridgeInvocationResult:
    """Normalized bridge-owned subprocess result for vendored front-door calls."""

    command: list[str] = field(default_factory=list)
    returncode: int | None = None
    stdout: str = ""
    stderr: str = ""
    raw_output: str = ""
    backend_failure: str | None = None
    front_door_mode: str = "vendored_runtime_binary"
    front_door_strategy: str = "bridge_selected"


def _truncate_log_value(value: str, limit: int = 240) -> str:
    compact = " ".join(value.split())
    if len(compact) <= limit:
        return compact
    return f"{compact[: limit - 3]}..."


def _describe_command(command: list[str]) -> dict[str, object]:
    return {
        "argv0": command[0] if command else None,
        "argv_count": len(command),
        "has_resume": "resume" in command,
        "has_json": "--json" in command,
        "has_ephemeral": "--ephemeral" in command,
    }


def get_codex_handoff_surface() -> CodexSnapshotBridgeSurface:
    """Return the only intended Mente-facing vendored bootstrap descriptor."""

    repo_root = Path(__file__).resolve().parents[3]
    upstream_root = repo_root / "kernel/codex/upstream"
    return CodexSnapshotBridgeSurface(
        upstream_root=upstream_root,
        bridge_root=repo_root / "kernel/codex/bridge",
        patch_root=repo_root / "kernel/codex/patches",
        rust_cli_entrypoint=upstream_root / "codex-rs/cli/src/main.rs",
        rust_exec_entrypoint=upstream_root / "codex-rs/exec/src/main.rs",
        python_sdk_root=upstream_root / "sdk/python/src",
        app_server_root=upstream_root / "sdk/python/src/codex_app_server",
        runtime_locator_module=repo_root / "kernel/codex/release/runtime.py",
        runtime_binary_path=expected_vendored_runtime_binary_path(repo_root),
    )


def _resolve_runtime_binary_path(
    *,
    codex_binary_override: str | Path | None = None,
) -> Path:
    if codex_binary_override is not None:
        return Path(codex_binary_override).expanduser()
    return resolve_vendored_runtime_binary()


def build_vendored_command(
    *,
    payload: KernelExecutionPayload,
    session: KernelSessionRequest,
    runtime_config: RuntimeConfig,
    sandbox: str,
    approval_policy: str,
    output_last_message: str | None = None,
    output_schema: str | None = None,
    workdir: str | None = None,
    add_dirs: list[str] | None = None,
    codex_binary_override: str | Path | None = None,
    json_output: bool = False,
) -> list[str]:
    """Build the bridge-owned vendored front-door command for one exec call."""

    command_path = _resolve_runtime_binary_path(
        codex_binary_override=codex_binary_override,
    )
    command = build_exec_command(
        codex_binary=str(command_path),
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
    if json_output:
        command.insert(3, "--json")
    return command


def invoke_vendored_front_door(
    *,
    payload: KernelExecutionPayload,
    session: KernelSessionRequest,
    runtime_config: RuntimeConfig,
    sandbox: str,
    approval_policy: str,
    cwd: str,
    workdir: str,
    output_last_message: str,
    output_schema: str,
    add_dirs: list[str] | None = None,
    codex_binary_override: str | Path | None = None,
    stdout_line_callback: Callable[[str], None] | None = None,
    cancel_event: threading.Event | None = None,
    subprocess_run: Any = subprocess.run,
    subprocess_popen: Any = subprocess.Popen,
) -> CodexBridgeInvocationResult:
    """Invoke the bridge-selected vendored front door for one exec request."""

    try:
        resolved_binary_path = _resolve_runtime_binary_path(
            codex_binary_override=codex_binary_override,
        )
    except RuntimeNotBootstrappedError as exc:
        return CodexBridgeInvocationResult(
            backend_failure=f"runtime_not_bootstrapped:{exc}",
        )

    command = build_vendored_command(
        payload=payload,
        session=session,
        runtime_config=runtime_config,
        sandbox=sandbox,
        approval_policy=approval_policy,
        output_last_message=output_last_message,
        output_schema=output_schema,
        workdir=workdir,
        add_dirs=add_dirs,
        codex_binary_override=resolved_binary_path,
        json_output=stdout_line_callback is not None or session.mode is not KernelSessionMode.STATELESS,
    )
    try:
        env = build_private_runtime_env(
            runtime_config.runtime_home,
            runtime_config.subprocess_env,
        )
        logger.info(
            "Mente vendored runtime launch: %s",
            {
                **_describe_command(command),
                "cwd": cwd,
                "workdir": workdir,
                "runtime_home": str(runtime_config.runtime_home),
                "session_mode": session.mode.value,
                "session_id_present": bool(session.session_id),
            },
        )
        if stdout_line_callback is None:
            completed = subprocess_run(
                command,
                capture_output=True,
                text=True,
                cwd=cwd,
                check=False,
                env=env,
                stdin=subprocess.DEVNULL,
            )
            cancelled = False
            logger.info(
                "Mente vendored runtime completed: %s",
                {
                    **_describe_command(command),
                    "returncode": completed.returncode,
                    "stdout_chars": len(completed.stdout or ""),
                    "stderr_chars": len(completed.stderr or ""),
                },
            )
        else:
            completed, cancelled = _run_streaming_subprocess(
                command=command,
                cwd=cwd,
                env=env,
                stdout_line_callback=stdout_line_callback,
                cancel_event=cancel_event,
                subprocess_popen=subprocess_popen,
            )
    except OSError as exc:
        return CodexBridgeInvocationResult(
            command=command,
            backend_failure=f"spawn_error:{type(exc).__name__}:{exc}",
        )

    output_path = Path(output_last_message)
    raw_output = ""
    if output_path.exists():
        raw_output = output_path.read_text(encoding="utf-8").strip()

    return CodexBridgeInvocationResult(
        command=command,
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
        raw_output=raw_output,
        backend_failure="interrupted_by_user" if cancelled else None,
    )


def _run_streaming_subprocess(
    *,
    command: list[str],
    cwd: str,
    env: dict[str, str],
    stdout_line_callback: Callable[[str], None],
    cancel_event: threading.Event | None,
    subprocess_popen: Any,
) -> tuple[subprocess.CompletedProcess[str], bool]:
    process = subprocess_popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=cwd,
        env=env,
        bufsize=1,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
    )
    stdout_lines: list[str] = []
    stderr_lines: list[str] = []
    cancelled = False
    started_at = time.monotonic()
    first_stdout_at: float | None = None
    first_stderr_at: float | None = None
    last_stdout_line: str | None = None
    last_stderr_line: str | None = None

    def _read_stdout() -> None:
        nonlocal first_stdout_at, last_stdout_line
        if process.stdout is None:
            return
        for line in process.stdout:
            stdout_lines.append(line)
            stripped = line.rstrip("\r\n")
            if first_stdout_at is None:
                first_stdout_at = time.monotonic()
                logger.info(
                    "Mente vendored runtime first stdout line after %.3fs: %s",
                    first_stdout_at - started_at,
                    _truncate_log_value(stripped),
                )
            if stripped:
                last_stdout_line = stripped
                stdout_line_callback(stripped)

    def _read_stderr() -> None:
        nonlocal first_stderr_at, last_stderr_line
        if process.stderr is None:
            return
        for line in process.stderr:
            stderr_lines.append(line)
            stripped = line.rstrip("\r\n")
            if first_stderr_at is None:
                first_stderr_at = time.monotonic()
                logger.warning(
                    "Mente vendored runtime first stderr line after %.3fs: %s",
                    first_stderr_at - started_at,
                    _truncate_log_value(stripped),
                )
            if stripped:
                last_stderr_line = stripped

    stdout_thread = threading.Thread(target=_read_stdout, daemon=True)
    stderr_thread = threading.Thread(target=_read_stderr, daemon=True)
    stdout_thread.start()
    stderr_thread.start()
    process_pid = getattr(process, "pid", None)
    process_group_id = _resolve_process_group_id(process_pid)
    logger.info(
        "Mente vendored runtime subprocess spawned: %s",
        {
            **_describe_command(command),
            "pid": process_pid,
            "pgid": process_group_id,
            "cwd": cwd,
        },
    )
    returncode: int | None = None
    while True:
        if cancel_event is not None and cancel_event.is_set():
            cancelled = True
            elapsed = time.monotonic() - started_at
            logger.warning(
                "Mente vendored runtime cancellation requested: %s",
                {
                    "pid": process_pid,
                    "elapsed_s": round(elapsed, 3),
                    "stdout_lines": len(stdout_lines),
                    "stderr_lines": len(stderr_lines),
                    "first_stdout_s": None if first_stdout_at is None else round(first_stdout_at - started_at, 3),
                    "first_stderr_s": None if first_stderr_at is None else round(first_stderr_at - started_at, 3),
                    "last_stdout": _truncate_log_value(last_stdout_line or ""),
                    "last_stderr": _truncate_log_value(last_stderr_line or ""),
                },
            )
            try:
                _signal_process(process, process_group_id, signal.SIGTERM)
                returncode = process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                _signal_process(process, process_group_id, signal.SIGKILL)
                returncode = process.wait(timeout=1)
            break
        returncode = process.poll()
        if returncode is not None:
            break
        time.sleep(0.05)
    stdout_thread.join()
    stderr_thread.join()
    elapsed = time.monotonic() - started_at
    logger.info(
        "Mente vendored runtime subprocess finished: %s",
        {
            "pid": process_pid,
            "pgid": process_group_id,
            "returncode": returncode,
            "cancelled": cancelled,
            "elapsed_s": round(elapsed, 3),
            "stdout_lines": len(stdout_lines),
            "stderr_lines": len(stderr_lines),
            "first_stdout_s": None if first_stdout_at is None else round(first_stdout_at - started_at, 3),
            "first_stderr_s": None if first_stderr_at is None else round(first_stderr_at - started_at, 3),
            "last_stdout": _truncate_log_value(last_stdout_line or ""),
            "last_stderr": _truncate_log_value(last_stderr_line or ""),
        },
    )
    return subprocess.CompletedProcess(
        command,
        returncode,
        stdout="".join(stdout_lines),
        stderr="".join(stderr_lines),
    ), cancelled


def _resolve_process_group_id(process_pid: int | None) -> int | None:
    if process_pid is None or not hasattr(os, "getpgid"):
        return None
    try:
        return os.getpgid(process_pid)
    except OSError:
        return None


def _signal_process(process: Any, process_group_id: int | None, sig: signal.Signals) -> None:
    if process_group_id is not None and hasattr(os, "killpg"):
        try:
            os.killpg(process_group_id, sig)
            return
        except ProcessLookupError:
            return
        except OSError:
            logger.debug(
                "Mente vendored runtime group signal failed; falling back to direct process signal",
                exc_info=True,
            )

    if sig == signal.SIGTERM and hasattr(process, "terminate"):
        process.terminate()
        return
    if sig == signal.SIGKILL and hasattr(process, "kill"):
        process.kill()
        return
    if hasattr(process, "terminate"):
        process.terminate()
