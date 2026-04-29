"""Minimal Codex-backed executor for Mente."""

from __future__ import annotations

import json
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
        output_schema: str | None = None,
    ) -> list[str]:
        """Build the Codex CLI command for a request."""
        command = [self.codex_binary, "exec"]
        command.extend(self._build_execution_mode_args())
        command.extend(
            [
                "--skip-git-repo-check",
                "--color",
                "never",
                "--cd",
                request.workspace,
            ]
        )
        if output_last_message:
            command.extend(["--output-last-message", output_last_message])
        if output_schema:
            command.extend(["--output-schema", output_schema])
        command.append(self.build_prompt(request))
        return command

    def _build_execution_mode_args(self) -> list[str]:
        """Map legacy sandbox/approval settings onto the current Codex CLI."""
        if self.approval_policy == "never":
            if self.sandbox == "danger-full-access":
                return ["--dangerously-bypass-approvals-and-sandbox"]
            return ["--sandbox", self.sandbox, "--full-auto"]

        return ["--sandbox", self.sandbox]

    def execute(self, request: ExecutionRequest) -> ExecutionResult:
        """Run Codex synchronously and normalize the response."""
        output_path: Path | None = None
        schema_path: Path | None = None
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
                json.dump(self._structured_output_schema(), handle)
                schema_path = Path(handle.name)

            command = self.build_command(
                request,
                output_last_message=str(output_path),
                output_schema=str(schema_path),
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
            memory_candidates: list[str] = []
            structured_output = None
            if output_path.exists():
                raw_output = output_path.read_text(encoding="utf-8").strip()
                structured_output = self._parse_structured_output(raw_output)
                if structured_output is not None:
                    summary = structured_output.get("assistant_summary", "").strip()
                    memory_candidates = [
                        candidate.strip()
                        for candidate in structured_output.get("memory_candidates", [])
                        if isinstance(candidate, str) and candidate.strip()
                    ]
                else:
                    summary = raw_output
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
                memory_candidates=memory_candidates,
                failure_reason=None if completed.returncode == 0 else f"exit_code:{completed.returncode}",
                metadata={
                    "returncode": completed.returncode,
                    "stdout": completed.stdout,
                    "stderr": completed.stderr,
                    "structured_output": structured_output,
                },
            )
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

    def _structured_output_schema(self) -> dict[str, object]:
        """Return the schema used for final structured Codex responses."""
        return {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "assistant_summary": {"type": "string"},
                "memory_candidates": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
            "required": ["assistant_summary", "memory_candidates"],
        }

    def _parse_structured_output(self, raw_output: str) -> dict[str, object] | None:
        """Parse structured Codex output and fall back cleanly on malformed data."""
        if not raw_output:
            return None

        try:
            parsed = json.loads(raw_output)
        except json.JSONDecodeError:
            return None

        if not isinstance(parsed, dict):
            return None

        if not isinstance(parsed.get("assistant_summary"), str):
            return None
        if not isinstance(parsed.get("memory_candidates"), list):
            return None

        return parsed
