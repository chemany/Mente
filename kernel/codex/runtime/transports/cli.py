"""CLI-backed temporary transport for the vendored Codex kernel runner."""

from __future__ import annotations

import subprocess
from pathlib import Path

from kernel.codex.runtime.launcher import build_private_runtime_env, build_stateless_command
from kernel.codex.runtime.transport import (
    KernelTransport,
    KernelTransportRequest,
    KernelTransportResponse,
)


class CliKernelTransport(KernelTransport):
    """Execute kernel transport requests through the public ``codex`` CLI."""

    def __init__(self, codex_binary: str = "codex") -> None:
        self.codex_binary = codex_binary

    def execute(self, request: KernelTransportRequest) -> KernelTransportResponse:
        command = build_stateless_command(
            codex_binary=self.codex_binary,
            payload=request.payload,
            session=request.session,
            sandbox=request.sandbox,
            approval_policy=request.approval_policy,
            runtime_config=request.runtime_config,
            output_last_message=request.output_last_message,
            output_schema=request.output_schema,
            workdir=request.workdir,
            add_dirs=request.add_dirs,
        )
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                cwd=request.cwd,
                check=False,
                env=build_private_runtime_env(
                    request.runtime_config.runtime_home,
                    request.runtime_config.subprocess_env,
                ),
            )
        except OSError as exc:
            return KernelTransportResponse(
                command=command,
                stdout="",
                stderr="",
                raw_output="",
                backend_failure=f"spawn_error:{type(exc).__name__}:{exc}",
            )

        raw_output = ""
        output_path = Path(request.output_last_message)
        if output_path.exists():
            raw_output = output_path.read_text(encoding="utf-8").strip()

        return KernelTransportResponse(
            command=command,
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
            raw_output=raw_output,
        )
