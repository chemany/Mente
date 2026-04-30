"""Minimal Codex-backed executor for Mente."""

from __future__ import annotations

from collections.abc import Callable
import logging
import os
import shutil
from pathlib import Path
from typing import Any

from kernel.codex.runtime.launcher import build_private_runtime_env, build_stateless_command
from kernel.codex.runtime.protocol import KernelExecutionPayload
from kernel.codex.runtime.result import KernelExecutionResult
from kernel.codex.runtime.runner import KernelRunner
from kernel.codex.session.protocol import KernelSessionMode, KernelSessionRequest
from mente.executors.kernel_adapter import CodexKernelAdapter
from mente.executors.prompting import render_execution_prompt
from mente.executors.runtime_config import RuntimeConfig, resolve_runtime_config
from mente.task_core.models import ExecutionRequest, ExecutionResult

logger = logging.getLogger(__name__)


class CodexExecutor(CodexKernelAdapter):
    """Execute Mente requests through the vendored Codex kernel runner."""

    def __init__(
        self,
        codex_binary: str = "codex",
        sandbox: str = "workspace-write",
        approval_policy: str = "never",
        runtime_config: RuntimeConfig | None = None,
        runtime_config_resolver: Callable[[str | Path], RuntimeConfig] | None = None,
        runner: Any | None = None,
    ) -> None:
        self.codex_binary = codex_binary
        self.sandbox = sandbox
        self.approval_policy = approval_policy
        self._runtime_config = runtime_config
        self._runtime_config_resolver = runtime_config_resolver or resolve_runtime_config
        self._runner = runner or KernelRunner(
            codex_binary=codex_binary,
            sandbox=sandbox,
            approval_policy=approval_policy,
        )

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
        """Build the Codex CLI command for a request through the vendored launcher."""
        resolved_runtime_config = runtime_config or self._resolve_runtime_config(request.workspace)
        if config_overrides is not None:
            resolved_runtime_config = RuntimeConfig(
                runtime_home=resolved_runtime_config.runtime_home,
                ignore_user_config=resolved_runtime_config.ignore_user_config,
                ignore_rules=resolved_runtime_config.ignore_rules,
                codex_config=resolved_runtime_config.codex_config,
            )
        return build_stateless_command(
            codex_binary=self.codex_binary,
            payload=self._build_kernel_payload(request),
            session=KernelSessionRequest(mode=KernelSessionMode.STATELESS),
            sandbox=self.sandbox,
            approval_policy=self.approval_policy,
            runtime_config=resolved_runtime_config,
            output_last_message=output_last_message,
            output_schema=output_schema,
            workdir=workdir or request.workspace,
            add_dirs=add_dirs or [],
        )

    def execute(self, request: ExecutionRequest) -> ExecutionResult:
        """Run Codex through the vendored kernel runner and translate the result."""
        runtime_config = self._resolve_runtime_config(request.workspace)
        codex_home = runtime_config.runtime_home
        codex_home.mkdir(parents=True, exist_ok=True)
        self._seed_auth_into_isolated_home(codex_home)
        kernel_result = self._runner.run(
            payload=self._build_kernel_payload(request),
            session=self._build_session_request(request),
            runtime_config=runtime_config,
        )
        return self._translate_kernel_result(kernel_result)

    def _build_kernel_payload(self, request: ExecutionRequest) -> KernelExecutionPayload:
        """Translate the executor request into the vendored kernel payload."""
        return KernelExecutionPayload(
            prompt=self.build_prompt(request),
            workspace=request.workspace,
            tool_policy=self.resolve_tool_policy(request),
        )

    def _build_session_request(self, request: ExecutionRequest) -> KernelSessionRequest:
        """Build the explicit kernel session envelope while keeping production stateless by default."""
        execution_mode = (request.execution_mode or "").strip().lower()
        if execution_mode == KernelSessionMode.SESSION.value or request.resume_token:
            return KernelSessionRequest(
                mode=KernelSessionMode.SESSION,
                session_id=request.session_id,
                resume_token=request.resume_token,
            )
        return KernelSessionRequest(mode=KernelSessionMode.STATELESS)

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

    def _translate_kernel_result(self, result: KernelExecutionResult) -> ExecutionResult:
        """Translate the vendored kernel result back into the Mente executor contract."""
        return ExecutionResult(
            status=result.status,
            summary=result.assistant_summary,
            commands_run=list(result.commands_run),
            memory_candidates=list(result.memory_candidates),
            failure_reason=result.backend_failure,
            metadata=dict(result.debug),
        )
