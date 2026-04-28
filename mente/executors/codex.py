"""Minimal Codex-backed executor for Mente."""

from __future__ import annotations

import logging
import os
import shlex
import subprocess
import tempfile
from pathlib import Path

from mente.executors.base import Executor
from mente.executors.prompting import render_execution_prompt
from mente.task_core.models import ExecutionRequest, ExecutionResult

logger = logging.getLogger(__name__)


class CodexExecutor(Executor):
    """Execute Mente requests through the Codex CLI."""

    def __init__(
        self,
        codex_binary: str = "codex",
        sandbox: str = "workspace-write",
        approval_policy: str = "never",
    ) -> None:
        self.codex_binary = codex_binary
        self.sandbox = sandbox
        self.approval_policy = approval_policy

    def build_prompt(self, request: ExecutionRequest) -> str:
        """Build a stable textual prompt from an execution request."""
        return render_execution_prompt(request)

    def build_command(
        self,
        request: ExecutionRequest,
        output_last_message: str | None = None,
    ) -> list[str]:
        """Build the Codex CLI command for a request."""
        command = [
            self.codex_binary,
            "exec",
            "--sandbox",
            self.sandbox,
            "--ask-for-approval",
            self.approval_policy,
            "--skip-git-repo-check",
            "--color",
            "never",
            "--cd",
            request.workspace,
        ]
        if output_last_message:
            command.extend(["--output-last-message", output_last_message])
        command.append(self.build_prompt(request))
        return command

    def execute(self, request: ExecutionRequest) -> ExecutionResult:
        """Run Codex synchronously and normalize the response."""
        output_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                prefix="mente-codex-",
                suffix=".txt",
                delete=False,
            ) as handle:
                output_path = Path(handle.name)

            command = self.build_command(
                request,
                output_last_message=str(output_path),
            )
            try:
                completed = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    cwd=request.workspace,
                    check=False,
                )
            except OSError as exc:
                logger.error(
                    "codex execution failed to start for task %s in %s: %s",
                    request.task_id,
                    request.workspace,
                    exc,
                )
                return ExecutionResult(
                    status="failed",
                    summary=str(exc),
                    commands_run=[shlex.join(command)],
                    failure_reason="spawn_error",
                    metadata={
                        "exception_type": type(exc).__name__,
                        "exception": str(exc),
                    },
                )

            summary = ""
            if output_path.exists():
                summary = output_path.read_text(encoding="utf-8").strip()
            if not summary:
                summary = (completed.stdout or completed.stderr).strip()

            status = "success" if completed.returncode == 0 else "failed"
            logger.info(
                "codex execution finished for task %s in %s with status %s and exit code %s",
                request.task_id,
                request.workspace,
                status,
                completed.returncode,
            )
            return ExecutionResult(
                status=status,
                summary=summary,
                commands_run=[shlex.join(command)],
                failure_reason=None if completed.returncode == 0 else f"exit_code:{completed.returncode}",
                metadata={
                    "returncode": completed.returncode,
                    "stdout": completed.stdout,
                    "stderr": completed.stderr,
                },
            )
        finally:
            if output_path is not None:
                try:
                    os.unlink(output_path)
                except FileNotFoundError:
                    pass
