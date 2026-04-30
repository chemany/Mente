"""Vendored execution runner for the Codex kernel slice."""

from __future__ import annotations

import json
import os
import shlex
import shutil
import tempfile
from pathlib import Path
from typing import Any

from kernel.codex.runtime.protocol import build_structured_output_schema, parse_structured_output
from kernel.codex.runtime.result import KernelExecutionResult
from kernel.codex.runtime.transport import KernelTransport, KernelTransportRequest
from kernel.codex.runtime.transports.cli import CliKernelTransport
from kernel.codex.sandbox.workspace import prepare_isolated_workspace
from kernel.codex.session.protocol import KernelSessionMode, KernelSessionRequest


class KernelRunner:
    """Own stateless execution orchestration for vendored kernel runs."""

    def __init__(
        self,
        transport: KernelTransport | None = None,
        *,
        codex_binary: str = "codex",
        sandbox: str = "workspace-write",
        approval_policy: str = "never",
    ) -> None:
        self.transport = transport or CliKernelTransport(codex_binary=codex_binary)
        self.sandbox = sandbox
        self.approval_policy = approval_policy

    def run(
        self,
        *,
        payload,
        session: KernelSessionRequest,
        runtime_config: Any,
    ) -> KernelExecutionResult:
        if session.mode is not KernelSessionMode.STATELESS:
            return KernelExecutionResult(
                status="failed",
                assistant_summary="Kernel session mode is recognized but not enabled for production execution yet.",
                backend_failure="unsupported_session_mode",
                debug={"session_mode": session.mode.value, "session_id": session.session_id},
            )

        output_path: Path | None = None
        schema_path: Path | None = None
        runtime_workdir: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                prefix="mente-codex-",
                suffix=".txt",
                delete=False,
            ) as handle:
                output_path = Path(handle.name)
            with tempfile.NamedTemporaryFile(
                prefix="mente-codex-schema-",
                suffix=".json",
                mode="w",
                encoding="utf-8",
                delete=False,
            ) as handle:
                json.dump(build_structured_output_schema(), handle)
                schema_path = Path(handle.name)

            runtime_workdir = prepare_isolated_workspace()
            response = self.transport.execute(
                KernelTransportRequest(
                    payload=payload,
                    session=session,
                    runtime_config=runtime_config,
                    sandbox=self.sandbox,
                    approval_policy=self.approval_policy,
                    cwd=payload.workspace,
                    workdir=str(runtime_workdir),
                    output_last_message=str(output_path),
                    output_schema=str(schema_path),
                    add_dirs=[str(Path(payload.workspace).resolve())],
                )
            )
            return self._normalize_transport_response(response)
        finally:
            if output_path is not None:
                try:
                    os.unlink(output_path)
                except FileNotFoundError:
                    pass
            if schema_path is not None:
                try:
                    os.unlink(schema_path)
                except FileNotFoundError:
                    pass
            if runtime_workdir is not None:
                shutil.rmtree(runtime_workdir, ignore_errors=True)

    def _normalize_transport_response(self, response) -> KernelExecutionResult:
        structured_output = parse_structured_output(response.raw_output)
        memory_candidates: list[str] = []
        assistant_summary = response.raw_output
        structured_payload = None
        if structured_output is not None:
            structured_payload = structured_output.model_dump(mode="json")
            assistant_summary = structured_output.assistant_summary.strip()
            memory_candidates = [
                candidate.strip()
                for candidate in structured_output.memory_candidates
                if candidate.strip()
            ]

        if not assistant_summary:
            assistant_summary = (response.stdout or response.stderr or response.backend_failure or "").strip()

        status = "success"
        backend_failure = response.backend_failure
        if backend_failure:
            status = "failed"
        elif response.returncode not in (0, None):
            status = "failed"
            backend_failure = f"exit_code:{response.returncode}"

        return KernelExecutionResult(
            status=status,
            assistant_summary=assistant_summary,
            memory_candidates=memory_candidates,
            commands_run=[shlex.join(response.command)] if response.command else [],
            debug={
                "returncode": response.returncode,
                "stdout": response.stdout,
                "stderr": response.stderr,
                "structured_output": structured_payload,
            },
            backend_failure=backend_failure,
        )
