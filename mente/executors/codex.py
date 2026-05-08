"""Minimal Codex-backed executor for Mente."""

from __future__ import annotations

from collections.abc import Callable
import logging
import os
import shutil
from pathlib import Path
from typing import Any

from hermes_constants import get_skills_dir
from kernel.codex.bridge.entrypoints import build_vendored_command
from kernel.codex.runtime.launcher import build_private_runtime_env
from kernel.codex.runtime.protocol import KernelExecutionPayload
from kernel.codex.runtime.result import KernelExecutionResult
from kernel.codex.runtime.runner import KernelRunner
from kernel.codex.session.protocol import KernelSessionMode, KernelSessionRequest
from mente.execution_events import ExecutionEventCallback, emit_execution_event
from mente.executors.bridge_mcp import augment_runtime_config_for_bridge_tools
from mente.executors.kernel_adapter import CodexKernelAdapter
from mente.executors.prompting import (
    build_prompt_metrics,
    normalize_user_facing_summary,
    render_execution_prompt,
)
from mente.executors.runtime_auth import write_private_runtime_auth
from mente.executors.runtime_config import (
    RuntimeConfig,
    adapt_runtime_config_for_request,
    resolve_runtime_config,
)
from mente.feature_flags import (
    is_sessionful_execution_enabled,
    sessionful_execution_sources,
)
from mente.memory.context import resolve_memory_context, resolve_memory_read_mode, uses_on_demand_memory
from mente.memory.policy import MemoryPolicyResolver
from mente.memory.repository import MemoryRepository
from mente.task_core.models import (
    ExecutionMode,
    ExecutionRequest,
    ExecutionResult,
    SessionMode,
)

logger = logging.getLogger(__name__)


class CodexExecutor(CodexKernelAdapter):
    """Execute Mente requests through the vendored Codex kernel runner."""

    def __init__(
        self,
        codex_binary: str | None = None,
        sandbox: str = "workspace-write",
        approval_policy: str = "never",
        runtime_config: RuntimeConfig | None = None,
        runtime_config_resolver: Callable[[str | Path], RuntimeConfig] | None = None,
        runner: Any | None = None,
        memory_repository: MemoryRepository | None = None,
        memory_limit: int = 5,
        memory_policy_resolver: MemoryPolicyResolver | None = None,
        event_callback: ExecutionEventCallback | None = None,
        cancel_event: Any | None = None,
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
            event_callback=event_callback,
            cancel_event=cancel_event,
        )
        self._memory_repository = memory_repository
        self._memory_limit = memory_limit
        self._memory_policy_resolver = memory_policy_resolver
        self._event_callback = event_callback

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
        """Build the bridge-owned vendored command for a request."""
        resolved_runtime_config = runtime_config or self._resolve_runtime_config_for_request(request)
        if config_overrides is not None:
            resolved_runtime_config = RuntimeConfig(
                runtime_home=resolved_runtime_config.runtime_home,
                ignore_user_config=resolved_runtime_config.ignore_user_config,
                ignore_rules=resolved_runtime_config.ignore_rules,
                codex_config=resolved_runtime_config.codex_config,
                subprocess_env=resolved_runtime_config.subprocess_env,
            )
        resolved_runtime_config = augment_runtime_config_for_bridge_tools(
            resolved_runtime_config,
            request,
        )
        session_request = self._build_session_request(request)
        return build_vendored_command(
            payload=self._build_kernel_payload(request),
            session=session_request,
            sandbox=self.sandbox,
            approval_policy=self.approval_policy,
            runtime_config=resolved_runtime_config,
            output_last_message=output_last_message,
            output_schema=output_schema,
            workdir=workdir or request.workspace,
            add_dirs=add_dirs or [],
            codex_binary_override=self.codex_binary,
        )

    def execute(self, request: ExecutionRequest) -> ExecutionResult:
        """Run Codex through the vendored kernel runner and translate the result."""
        enriched_request = self._prepare_request(request)
        emit_execution_event(
            self._event_callback,
            "executor.memory_context_resolved",
            {
                "task_id": enriched_request.task_id,
                "session_id": enriched_request.session_id,
                "injected_count": len(enriched_request.memory_facts),
                "memory_read_mode": enriched_request.metadata.get("memory_read_mode"),
            },
            logger=logger,
        )
        emit_execution_event(
            self._event_callback,
            "executor.prompt_prepared",
            {
                "task_id": request.task_id,
                "session_id": request.session_id,
                **build_prompt_metrics(enriched_request),
            },
            logger=logger,
        )
        runtime_config = self._resolve_runtime_config_for_request(enriched_request)
        runtime_config = augment_runtime_config_for_bridge_tools(
            runtime_config,
            enriched_request,
        )
        emit_execution_event(
            self._event_callback,
            "executor.runtime_config_resolved",
            {
                "task_id": request.task_id,
                "session_id": request.session_id,
                "runtime_home": str(runtime_config.runtime_home),
            },
            logger=logger,
        )
        codex_home = runtime_config.runtime_home
        codex_home.mkdir(parents=True, exist_ok=True)
        self._seed_user_skills_into_isolated_home(codex_home)
        auth_source = self._seed_auth_into_isolated_home(codex_home, runtime_config)
        emit_execution_event(
            self._event_callback,
            "executor.auth_prepared",
            {
                "task_id": request.task_id,
                "session_id": request.session_id,
                "auth_source": auth_source,
            },
            logger=logger,
        )
        precondition_fallback_reason = self._session_precondition_fallback_reason(enriched_request)
        session_request = self._build_session_request(
            enriched_request,
            precondition_fallback_reason=precondition_fallback_reason,
        )
        kernel_result = self._runner.run(
            payload=self._build_kernel_payload(enriched_request),
            session=session_request,
            runtime_config=runtime_config,
        )
        runtime_fallback_reason: str | None = None
        if self._should_retry_stateless(enriched_request, session_request, kernel_result):
            runtime_fallback_reason = kernel_result.backend_failure or "resume_failed"
            fallback_request = self._build_resume_fallback_request(enriched_request)
            session_request = KernelSessionRequest(mode=KernelSessionMode.STATELESS)
            kernel_result = self._runner.run(
                payload=self._build_kernel_payload(fallback_request),
                session=session_request,
                runtime_config=runtime_config,
            )
        return self._translate_kernel_result(
            kernel_result,
            enriched_request,
            session_request,
            precondition_fallback_reason=precondition_fallback_reason,
            runtime_fallback_reason=runtime_fallback_reason,
        )

    def _prepare_request(self, request: ExecutionRequest) -> ExecutionRequest:
        """Resolve memory context once, preserving thin-prompt delivery when requested."""

        if bool(request.metadata.get("memory_context_prepared")):
            return request

        memory_facts, _trace = resolve_memory_context(
            request,
            memory_repository=self._memory_repository,
            memory_limit=self._memory_limit,
            memory_policy_resolver=self._memory_policy_resolver,
        )
        prepared_memory_facts = memory_facts
        memory_read_mode = resolve_memory_read_mode(request)
        if uses_on_demand_memory(request):
            prepared_memory_facts = list(request.memory_facts)
        metadata = dict(request.metadata)
        metadata["memory_context_prepared"] = True
        metadata["memory_read_mode"] = memory_read_mode
        return request.model_copy(
            update={
                "memory_facts": prepared_memory_facts,
                "metadata": metadata,
            }
        )

    def _build_kernel_payload(self, request: ExecutionRequest) -> KernelExecutionPayload:
        """Translate the executor request into the vendored kernel payload."""
        return KernelExecutionPayload(
            prompt=self.build_prompt(request),
            workspace=request.workspace,
            tool_policy=self.resolve_tool_policy(request),
        )

    def _build_session_request(
        self,
        request: ExecutionRequest,
        *,
        precondition_fallback_reason: str | None = None,
    ) -> KernelSessionRequest:
        """Build the explicit kernel session envelope while keeping production stateless by default."""
        if precondition_fallback_reason is not None:
            return KernelSessionRequest(mode=KernelSessionMode.STATELESS)

        if request.execution_session is not None and request.execution_session.mode is SessionMode.RESUME:
            return KernelSessionRequest(
                mode=KernelSessionMode.SESSION,
                session_id=request.execution_session.continuity_id,
            )
        if request.execution_mode is ExecutionMode.SESSIONFUL:
            return KernelSessionRequest(mode=KernelSessionMode.SESSION)
        return KernelSessionRequest(mode=KernelSessionMode.STATELESS)

    def _requested_session_mode(self, request: ExecutionRequest) -> str:
        if request.execution_mode is not ExecutionMode.SESSIONFUL:
            return ExecutionMode.STATELESS.value
        if request.execution_session is not None:
            return request.execution_session.mode.value
        return SessionMode.START.value

    def _source(self, request: ExecutionRequest) -> str:
        return str(request.metadata.get("source") or "").strip()

    def _session_capable(self, request: ExecutionRequest) -> bool:
        return isinstance(request.tool_policy, dict) and bool(request.tool_policy.get("session_capable"))

    def _session_precondition_fallback_reason(self, request: ExecutionRequest) -> str | None:
        """Return the fail-closed downgrade reason when continuity may not be used."""
        if request.execution_mode is not ExecutionMode.SESSIONFUL:
            return None
        if not is_sessionful_execution_enabled():
            return "feature_flag_disabled"
        if self._source(request) not in sessionful_execution_sources():
            return "source_not_allowed"
        if not self._session_capable(request):
            return "session_not_capable"
        return None

    def _should_retry_stateless(
        self,
        request: ExecutionRequest,
        session_request: KernelSessionRequest,
        result: KernelExecutionResult,
    ) -> bool:
        """Retry as stateless only for bounded resume failures."""
        return (
            session_request.mode is KernelSessionMode.SESSION
            and request.execution_session is not None
            and request.execution_session.mode is SessionMode.RESUME
            and result.status != "success"
        )

    def _build_resume_fallback_request(self, request: ExecutionRequest) -> ExecutionRequest:
        """Synthesize the stateless retry request for bounded resume failures."""
        fallback_history_fact = str(request.metadata.get("fallback_history_fact") or "").strip()
        memory_facts = list(request.memory_facts)
        if fallback_history_fact and fallback_history_fact not in memory_facts:
            memory_facts.append(fallback_history_fact)
        return request.model_copy(
            update={
                "execution_mode": ExecutionMode.STATELESS,
                "execution_session": None,
                "memory_facts": memory_facts,
            }
        )

    def _execution_session_metadata(
        self,
        request: ExecutionRequest,
        session_request: KernelSessionRequest,
        result: ExecutionResult,
        *,
        precondition_fallback_reason: str | None = None,
        runtime_fallback_reason: str | None = None,
    ) -> dict[str, str | bool | None]:
        requested_mode = self._requested_session_mode(request)
        source = self._source(request)
        session_capable = self._session_capable(request)
        fallback_reason = runtime_fallback_reason or precondition_fallback_reason
        if fallback_reason is not None:
            return {
                "mode": ExecutionMode.STATELESS.value,
                "requested_mode": requested_mode,
                "effective_mode": ExecutionMode.STATELESS.value,
                "source": source,
                "session_capable": session_capable,
                "continuity_id": None,
                "continuity_status": "fallback_stateless",
                "fallback_reason": fallback_reason,
            }
        if session_request.mode is not KernelSessionMode.SESSION:
            return {
                "mode": ExecutionMode.STATELESS.value,
                "requested_mode": requested_mode,
                "effective_mode": ExecutionMode.STATELESS.value,
                "source": source,
                "session_capable": session_capable,
                "continuity_id": None,
                "continuity_status": "stateless",
                "fallback_reason": None,
            }
        continuity_candidate = result.metadata.get("thread_id")
        if continuity_candidate is None and request.execution_session is not None:
            continuity_candidate = request.execution_session.continuity_id
        continuity_id = str(continuity_candidate or "").strip()
        effective_mode = SessionMode.START.value
        continuity_status = "started"
        if request.execution_session is not None and request.execution_session.mode is SessionMode.RESUME:
            effective_mode = SessionMode.RESUME.value
            continuity_status = "resumed"
        if not continuity_id:
            continuity_status = "missing_continuity_id"
            fallback_reason = "missing_thread_id"
        return {
            "mode": effective_mode,
            "requested_mode": requested_mode,
            "effective_mode": effective_mode,
            "source": source,
            "session_capable": session_capable,
            "continuity_id": continuity_id or None,
            "continuity_status": continuity_status,
            "fallback_reason": fallback_reason,
        }

    def _build_subprocess_env(self, codex_home: Path) -> dict[str, str]:
        """Construct a minimal subprocess environment for isolated Codex runs."""
        runtime_config = self._runtime_config
        extra_env = runtime_config.subprocess_env if runtime_config is not None else None
        return build_private_runtime_env(codex_home, extra_env)

    def _seed_auth_into_isolated_home(self, codex_home: Path, runtime_config: RuntimeConfig) -> str:
        """Materialize private Codex auth into the isolated runtime home."""
        if runtime_config.subprocess_env.get("MENTE_CODEX_API_KEY"):
            return "private_env"
        return write_private_runtime_auth(codex_home)

    def _seed_user_skills_into_isolated_home(self, codex_home: Path) -> str:
        """Expose Mente-managed user skills inside the private Codex runtime home."""
        user_skills = get_skills_dir()
        bundled_skills = Path(__file__).resolve().parents[2] / "skills"
        target_skills = codex_home / ".agents" / "skills"
        has_user_skills = user_skills.is_dir()
        has_bundled_skills = bundled_skills.is_dir()
        if not has_user_skills and not has_bundled_skills:
            self._remove_runtime_path(target_skills)
            return "missing"
        if has_user_skills and has_bundled_skills:
            self._remove_runtime_path(target_skills)
            target_skills.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(bundled_skills, target_skills, symlinks=True)
            shutil.copytree(user_skills, target_skills, symlinks=True, dirs_exist_ok=True)
            return "merged_copy"
        source_skills = user_skills if has_user_skills else bundled_skills
        if target_skills.is_symlink():
            try:
                if target_skills.resolve() == source_skills.resolve():
                    return "symlink"
            except OSError:
                pass
        self._remove_runtime_path(target_skills)
        target_skills.parent.mkdir(parents=True, exist_ok=True)
        try:
            target_skills.symlink_to(source_skills, target_is_directory=True)
            return "symlink"
        except OSError:
            shutil.copytree(source_skills, target_skills, symlinks=True)
            return "copy"

    def _remove_runtime_path(self, path: Path) -> None:
        """Remove a Mente-managed file, symlink, or directory under the runtime home."""
        if path.is_symlink() or path.is_file():
            path.unlink(missing_ok=True)
            return
        if path.exists():
            shutil.rmtree(path)

    def _resolve_runtime_config(self, workspace: str | Path) -> RuntimeConfig:
        """Resolve the private runtime config for this executor instance."""
        if self._runtime_config is not None:
            return self._runtime_config
        return self._runtime_config_resolver(workspace)

    def _resolve_runtime_config_for_request(self, request: ExecutionRequest) -> RuntimeConfig:
        """Resolve workspace config, then apply request-scoped runtime hints."""

        return adapt_runtime_config_for_request(
            self._resolve_runtime_config(request.workspace),
            request,
        )

    def _translate_kernel_result(
        self,
        result: KernelExecutionResult,
        request: ExecutionRequest,
        session_request: KernelSessionRequest,
        *,
        precondition_fallback_reason: str | None = None,
        runtime_fallback_reason: str | None = None,
    ) -> ExecutionResult:
        """Translate the vendored kernel result back into the Mente executor contract."""
        translated = ExecutionResult(
            status=result.status,
            summary=normalize_user_facing_summary(
                result.assistant_summary,
                user_request=request.user_request,
            ),
            commands_run=list(result.commands_run),
            memory_candidates=list(result.memory_candidates),
            failure_reason=result.backend_failure,
            metadata=dict(result.debug),
        )
        translated.metadata["execution_session"] = self._execution_session_metadata(
            request,
            session_request,
            translated,
            precondition_fallback_reason=precondition_fallback_reason,
            runtime_fallback_reason=runtime_fallback_reason,
        )
        return translated
