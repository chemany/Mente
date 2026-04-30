"""Minimal Codex-backed executor for Mente."""

from __future__ import annotations

from collections.abc import Callable
import json
import logging
import os
import shlex
import shutil
import subprocess
import tempfile
from pathlib import Path

from kernel.codex.runtime.launcher import build_private_runtime_env, build_stateless_command
from kernel.codex.runtime.protocol import (
    KernelExecutionPayload,
    build_structured_output_schema,
    parse_structured_output,
)
from kernel.codex.session.protocol import KernelSessionRequest
from kernel.codex.sandbox.workspace import prepare_isolated_workspace
from mente.executors.kernel_adapter import CodexKernelAdapter
from mente.executors.prompting import render_execution_prompt
from mente.executors.runtime_config import RuntimeConfig, resolve_runtime_config
from mente.task_core.models import ExecutionRequest, ExecutionResult

logger = logging.getLogger(__name__)


class CodexExecutor(CodexKernelAdapter):
    """Execute Mente requests through the Codex CLI."""

    def __init__(
        self,
        codex_binary: str = "codex",
        sandbox: str = "workspace-write",
        approval_policy: str = "never",
        runtime_config: RuntimeConfig | None = None,
        runtime_config_resolver: Callable[[str | Path], RuntimeConfig] | None = None,
    ) -> None:
        self.codex_binary = codex_binary
        self.sandbox = sandbox
        self.approval_policy = approval_policy
        self._runtime_config = runtime_config
        self._runtime_config_resolver = runtime_config_resolver or resolve_runtime_config

    def build_prompt(self, request: ExecutionRequest) -> str:
        """Build a stable textual prompt from an execution request."""
        return render_execution_prompt(request)

    def build_request_payload(self, request: ExecutionRequest) -> dict[str, object]:
        """Build the stable adapter payload for a prepared execution request."""
        return self._build_kernel_payload(request).model_dump(mode="json")

    def build_command(
        self,
        request: ExecutionRequest,
        output_last_message: str | None = None,
        output_schema: str | None = None,
        config_overrides: list[str] | None = None,
        workdir: str | None = None,
        add_dirs: list[str] | None = None,
        runtime_config: RuntimeConfig | None = None,
    ) -> list[str]:
        """Build the Codex CLI command for a request."""
        payload = self.build_request_payload(request)
        runtime_config = runtime_config or self._resolve_runtime_config(request.workspace)
        command = [
            self.codex_binary,
            "exec",
            "--ephemeral",
        ]
        if runtime_config.ignore_user_config:
            command.append("--ignore-user-config")
        if runtime_config.ignore_rules:
            command.append("--ignore-rules")
        for override in config_overrides or []:
            command.extend(["-c", override])
        command.extend(self._build_execution_mode_args())
        command.extend(
            [
                "--skip-git-repo-check",
                "--color",
                "never",
                "--cd",
                workdir or request.workspace,
            ]
        )
        for add_dir in add_dirs or []:
            command.extend(["--add-dir", add_dir])
        if output_last_message:
            command.extend(["--output-last-message", output_last_message])
        if output_schema:
            command.extend(["--output-schema", output_schema])
        command.append(str(payload["prompt"]))
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
            runtime_config = self._resolve_runtime_config(request.workspace)
            codex_home = runtime_config.runtime_home
            codex_home.mkdir(parents=True, exist_ok=True)
            runtime_workdir = prepare_isolated_workspace()
            self._seed_auth_into_isolated_home(codex_home)
            command = build_stateless_command(
                codex_binary=self.codex_binary,
                payload=self._build_kernel_payload(request),
                session=self._build_session_request(),
                sandbox=self.sandbox,
                approval_policy=self.approval_policy,
                runtime_config=runtime_config,
                output_last_message=str(output_path),
                output_schema=str(schema_path),
                workdir=str(runtime_workdir),
                add_dirs=[str(Path(request.workspace).resolve())],
            )
            try:
                completed = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    cwd=request.workspace,
                    check=False,
                    env=build_private_runtime_env(codex_home),
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
                parsed_output = parse_structured_output(raw_output)
                structured_output = (
                    parsed_output.model_dump(mode="json")
                    if parsed_output is not None
                    else None
                )
                if structured_output is not None:
                    summary = parsed_output.assistant_summary.strip()
                    memory_candidates = [
                        candidate.strip()
                        for candidate in parsed_output.memory_candidates
                        if candidate.strip()
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
            if runtime_workdir is not None:
                shutil.rmtree(runtime_workdir, ignore_errors=True)

    def _build_kernel_payload(self, request: ExecutionRequest) -> KernelExecutionPayload:
        """Translate the executor request into the vendored kernel payload."""
        return KernelExecutionPayload(
            prompt=self.build_prompt(request),
            workspace=request.workspace,
            tool_policy=self.resolve_tool_policy(request),
        )

    def _build_session_request(self) -> KernelSessionRequest:
        """C1 keeps production execution stateless while using the vendored session envelope."""
        return KernelSessionRequest()

    def _build_subprocess_env(self, codex_home: Path) -> dict[str, str]:
        """Construct a minimal subprocess environment for isolated Codex runs."""
        return build_private_runtime_env(codex_home)

    def _seed_auth_into_isolated_home(self, codex_home: Path) -> None:
        """Copy only Codex auth material into the isolated runtime home."""
        source_auth = self._resolve_public_codex_home() / "auth.json"
        if not source_auth.exists():
            return
        target_auth = codex_home / "auth.json"
        shutil.copy2(source_auth, target_auth)
        target_auth.chmod(0o600)

    def _resolve_public_codex_home(self) -> Path:
        """Resolve the user's shared Codex home used only as an auth seed source."""
        configured = os.environ.get("CODEX_HOME", "").strip()
        if configured:
            return Path(configured).expanduser()
        return Path.home() / ".codex"

    def _resolve_runtime_config(self, workspace: str | Path) -> RuntimeConfig:
        """Resolve the private runtime config for this executor instance."""
        if self._runtime_config is not None:
            return self._runtime_config
        return self._runtime_config_resolver(workspace)
