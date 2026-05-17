"""Minimal Codex-backed executor for Mente."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import contextmanager
import json
import logging
import os
import re
import shlex
import shutil
import subprocess
from pathlib import Path
import sys
from typing import Any
from uuid import uuid4

from hermes_constants import get_mente_home, get_skills_dir
from kernel.codex.bridge.entrypoints import build_vendored_command
from kernel.codex.runtime.launcher import build_private_runtime_env
from kernel.codex.runtime.protocol import KernelExecutionPayload
from kernel.codex.runtime.result import KernelExecutionResult
from kernel.codex.runtime.runner import KernelRunner
from kernel.codex.session.protocol import KernelSessionMode, KernelSessionRequest
from mente.deep_research_paths import resolve_deep_research_output_root
from mente.execution_events import (
    ExecutionEventCallback,
    emit_execution_event,
    persist_lane_progress_event,
    persist_lane_terminal_event,
)
from mente.executors.bridge_mcp import augment_runtime_config_for_bridge_tools
from mente.executors.kernel_adapter import CodexKernelAdapter
from mente.executors.prompting import (
    build_prompt_metrics,
    normalize_user_facing_failure_summary,
    normalize_user_facing_summary,
    render_execution_prompt,
)
from mente.executors.responses_compat_bridge import (
    ResponsesCompatBridgeError,
    apply_responses_compat_bridge,
    start_responses_compat_bridge,
)
from mente.executors.runtime_auth import write_private_runtime_auth
from mente.executors.runtime_config import (
    ModelRuntime,
    RuntimeConfig,
    adapt_runtime_config_for_request,
    resolve_runtime_config,
)
from mente.feature_flags import (
    is_sessionful_execution_enabled,
    sessionful_execution_sources,
)
from mente.memory.context import (
    resolve_memory_context,
    resolve_memory_read_mode,
    retain_on_demand_prompt_memories,
    uses_on_demand_memory,
)
from mente.mente_inventory import build_worker_mente_inventory_payload
from mente.memory.policy import MemoryPolicyResolver
from mente.memory.repository import MemoryRepository
from mente.task_core.models import (
    ExecutionMode,
    ExecutionRequest,
    ExecutionResult,
    SessionMode,
)
from mente.task_core.repository import SQLiteTaskRepository

logger = logging.getLogger(__name__)

_DEEP_RESEARCH_TASK_PROFILE = "deep_research"
_SKILL_AUDIT_TASK_PROFILE = "skill_audit"
_DEEP_RESEARCH_REQUIRED_ARTIFACT_SUFFIXES: tuple[str, ...] = (".md", ".html", ".docx")
_ARTIFACT_PATH_PATTERN = re.compile(
    r"(?P<path>(?:~|/)[^\s<>()\[\]{}\"'`]+?\.(?:md|markdown|html|docx|doc|pdf|txt|csv|tsv|xlsx|xls|pptx|json|yaml|yml))",
    re.IGNORECASE,
)
_ARTIFACT_PATH_TRAILING_PUNCTUATION = ".,，。!！?？:：;；)]}>\"'"
_DEEP_RESEARCH_READ_ONLY_COMMAND_PREFIXES: tuple[str, ...] = (
    "cat ",
    "find ",
    "head ",
    "less ",
    "ls ",
    "more ",
    "pwd",
    "printf",
    "rg ",
    "sed ",
    "stat ",
    "tail ",
)
_DEEP_RESEARCH_DEFERRED_EXECUTION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bchecking (?:its|the) instructions first\b", re.IGNORECASE),
    re.compile(r"\bnext step\b", re.IGNORECASE),
    re.compile(r"\bnext i(?:'|’)m running\b", re.IGNORECASE),
    re.compile(r"\brun the provided parallel cli\b", re.IGNORECASE),
    re.compile(r"\brun the managed .*cli\b", re.IGNORECASE),
    re.compile(r"\bfull report workflow\b", re.IGNORECASE),
    re.compile(r"\bverify the generated artifacts\b", re.IGNORECASE),
    re.compile(r"\bverify markdown/html/docx artifacts\b", re.IGNORECASE),
    re.compile(r"\bstarted the managed deep-research workflow\b", re.IGNORECASE),
    re.compile(r"下一步"),
    re.compile(r"请继续执行深度研究工作流"),
    re.compile(r"继续执行深度研究工作流"),
)
_SKILL_AUDIT_PROBE_ONLY_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bnext step\b", re.IGNORECASE),
    re.compile(r"\bwill inspect\b", re.IGNORECASE),
    re.compile(r"\bcontinue (?:checking|reviewing|inspecting)\b", re.IGNORECASE),
    re.compile(r"\bi already read skill\.md\b", re.IGNORECASE),
    re.compile(r"\bstarting with the skill audit\b", re.IGNORECASE),
    re.compile(r"先按技能审查模式处理"),
    re.compile(r"我已经读了\s*SKILL\.md", re.IGNORECASE),
    re.compile(r"下一步"),
    re.compile(r"继续检查"),
)


class CodexExecutor(CodexKernelAdapter):
    """Execute Mente requests through the vendored Codex kernel runner."""

    _DEFAULT_SANDBOX = "workspace-write"
    _DEFAULT_APPROVAL_POLICY = "never"

    def __init__(
        self,
        codex_binary: str | None = None,
        sandbox: str | None = None,
        approval_policy: str | None = None,
        runtime_config: RuntimeConfig | None = None,
        runtime_config_resolver: Callable[[str | Path], RuntimeConfig] | None = None,
        runner: Any | None = None,
        memory_repository: MemoryRepository | None = None,
        memory_limit: int = 5,
        memory_policy_resolver: MemoryPolicyResolver | None = None,
        task_repository: SQLiteTaskRepository | None = None,
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
        self._task_repository = task_repository
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
                runtime_home_is_default=resolved_runtime_config.runtime_home_is_default,
                ignore_user_config=resolved_runtime_config.ignore_user_config,
                ignore_rules=resolved_runtime_config.ignore_rules,
                sandbox=resolved_runtime_config.sandbox,
                approval_policy=resolved_runtime_config.approval_policy,
                skip_git_repo_check=resolved_runtime_config.skip_git_repo_check,
                color=resolved_runtime_config.color,
                model_runtime=resolved_runtime_config.model_runtime,
                codex_config=resolved_runtime_config.codex_config,
                profile_overrides=resolved_runtime_config.profile_overrides,
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
            sandbox=self._resolve_sandbox(resolved_runtime_config),
            approval_policy=self._resolve_approval_policy(resolved_runtime_config),
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
        task_repository, owns_task_repository = self._resolve_task_repository()
        original_event_callback = self._event_callback
        original_runner_event_callback = getattr(self._runner, "event_callback", None)
        wrapped_event_callback = self._build_persistent_event_callback(
            enriched_request,
            task_repository=task_repository,
            original_callback=original_event_callback,
        )
        self._event_callback = wrapped_event_callback
        if hasattr(self._runner, "event_callback"):
            self._runner.event_callback = wrapped_event_callback
        translated_result: ExecutionResult | None = None
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
        try:
            if self._should_execute_managed_deep_research_directly(enriched_request):
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
                self._seed_canonical_memories_into_isolated_home(codex_home)
                self._seed_canonical_memory_aliases_into_isolated_home(codex_home)
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
                translated_result = self._execute_managed_deep_research_directly(
                    enriched_request,
                    runtime_config=runtime_config,
                )
                return translated_result
            with self._prepare_runtime_config_for_execution(runtime_config) as execution_runtime_config:
                emit_execution_event(
                    self._event_callback,
                    "executor.runtime_config_resolved",
                    {
                        "task_id": request.task_id,
                        "session_id": request.session_id,
                        "runtime_home": str(execution_runtime_config.runtime_home),
                    },
                    logger=logger,
                )
                codex_home = execution_runtime_config.runtime_home
                codex_home.mkdir(parents=True, exist_ok=True)
                self._seed_canonical_memories_into_isolated_home(codex_home)
                self._seed_canonical_memory_aliases_into_isolated_home(codex_home)
                self._seed_user_skills_into_isolated_home(codex_home)
                auth_source = self._seed_auth_into_isolated_home(codex_home, execution_runtime_config)
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
                deep_research_retry_metadata: dict[str, Any] | None = None
                skill_audit_retry_metadata: dict[str, Any] | None = None
                kernel_result = self._runner.run(
                    payload=self._build_kernel_payload(enriched_request),
                    session=session_request,
                    runtime_config=execution_runtime_config,
                )
                runtime_fallback_reason: str | None = None
                if self._should_retry_stateless(enriched_request, session_request, kernel_result):
                    runtime_fallback_reason = kernel_result.backend_failure or "resume_failed"
                    fallback_request = self._build_resume_fallback_request(enriched_request)
                    session_request = KernelSessionRequest(mode=KernelSessionMode.STATELESS)
                    kernel_result = self._runner.run(
                        payload=self._build_kernel_payload(fallback_request),
                        session=session_request,
                        runtime_config=execution_runtime_config,
                    )
                active_request = enriched_request
                while True:
                    retry_outcome = self._maybe_retry_deep_research_after_incomplete_turn(
                        request=active_request,
                        session_request=session_request,
                        kernel_result=kernel_result,
                        runtime_config=execution_runtime_config,
                    )
                    if retry_outcome is None:
                        break
                    kernel_result, session_request, active_request, deep_research_retry_metadata = (
                        retry_outcome
                    )
                while True:
                    retry_outcome = self._maybe_retry_skill_audit_after_incomplete_turn(
                        request=active_request,
                        session_request=session_request,
                        kernel_result=kernel_result,
                        runtime_config=execution_runtime_config,
                    )
                    if retry_outcome is None:
                        break
                    kernel_result, session_request, active_request, skill_audit_retry_metadata = (
                        retry_outcome
                    )
                translated_result = self._translate_kernel_result(
                    kernel_result,
                    active_request,
                    session_request,
                    model_name=execution_runtime_config.model_runtime.model,
                    precondition_fallback_reason=precondition_fallback_reason,
                    runtime_fallback_reason=runtime_fallback_reason,
                )
                if deep_research_retry_metadata is not None:
                    translated_result.metadata["deep_research_retry"] = deep_research_retry_metadata
                if skill_audit_retry_metadata is not None:
                    translated_result.metadata["skill_audit_retry"] = skill_audit_retry_metadata
                return translated_result
        except ResponsesCompatBridgeError as exc:
            translated_result = self._responses_compat_bridge_failure_result(runtime_config, exc)
            return translated_result
        finally:
            try:
                if translated_result is not None and task_repository is not None:
                    self._persist_terminal_lane_event(
                        enriched_request,
                        translated_result,
                        task_repository=task_repository,
                    )
            except Exception:
                logger.exception(
                    "failed to persist terminal lane event for task %s",
                    enriched_request.task_id,
                )
            self._event_callback = original_event_callback
            if hasattr(self._runner, "event_callback"):
                self._runner.event_callback = original_runner_event_callback
            if owns_task_repository and task_repository is not None:
                try:
                    task_repository.close()
                except Exception:
                    logger.exception(
                        "failed to close task repository for task %s",
                        enriched_request.task_id,
                    )

    def _resolve_task_repository(self) -> tuple[SQLiteTaskRepository | None, bool]:
        if self._task_repository is not None:
            return self._task_repository, False
        try:
            return SQLiteTaskRepository(), True
        except Exception:
            logger.exception("failed to open default task repository for execution-event persistence")
            return None, False

    def _build_persistent_event_callback(
        self,
        request: ExecutionRequest,
        *,
        task_repository: SQLiteTaskRepository | None,
        original_callback: ExecutionEventCallback | None,
    ) -> ExecutionEventCallback:
        lane = self._resolve_request_lane(request)
        job_id = self._resolve_request_job_id(request)
        skill_refs = list(request.worker_skill_refs or request.skill_refs)
        metadata = dict(request.metadata or {})

        def _callback(event_type: str, payload: dict[str, Any]) -> None:
            if original_callback is not None:
                try:
                    original_callback(event_type, payload)
                except Exception:
                    logger.exception("failed to forward execution event %s", event_type)
            if task_repository is None:
                return
            try:
                persist_lane_progress_event(
                    task_repository,
                    event_type=event_type,
                    payload=payload,
                    session_id=request.session_id,
                    lane=lane,
                    task_id=request.task_id,
                    job_id=job_id,
                    skill_refs=skill_refs,
                    metadata=metadata,
                )
            except Exception:
                logger.exception(
                    "failed to persist runtime lane event %s for task %s",
                    event_type,
                    request.task_id,
                )

        return _callback

    def _persist_terminal_lane_event(
        self,
        request: ExecutionRequest,
        result: ExecutionResult,
        *,
        task_repository: SQLiteTaskRepository,
    ) -> None:
        persist_lane_terminal_event(
            task_repository,
            result=result,
            session_id=request.session_id,
            lane=self._resolve_request_lane(request),
            task_id=request.task_id,
            job_id=self._resolve_request_job_id(request),
            skill_refs=list(request.worker_skill_refs or request.skill_refs),
            metadata=dict(request.metadata or {}),
        )

    def _resolve_request_lane(self, request: ExecutionRequest) -> str:
        lane = (
            request.worker_lane
            or str(request.metadata.get("lane") or "").strip()
            or "director"
        )
        return str(lane).strip().lower() or "director"

    def _resolve_request_job_id(self, request: ExecutionRequest) -> str | None:
        value = request.job_id or request.metadata.get("job_id")
        normalized = str(value or "").strip()
        return normalized or None

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
            prepared_memory_facts, _retained_char_count = retain_on_demand_prompt_memories(
                memory_facts=memory_facts,
                trace=_trace,
                task_memory_facts=list(request.memory_facts),
            )
        metadata = dict(request.metadata)
        inventory_payload = build_worker_mente_inventory_payload(request)
        if inventory_payload is not None:
            inventory_fact, inventory_metadata = inventory_payload
            if inventory_fact and not any(
                fact.startswith("Mente inventory:") for fact in prepared_memory_facts
            ):
                prepared_memory_facts = [*prepared_memory_facts, inventory_fact]
            metadata.setdefault("mente_inventory", inventory_metadata)
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

    def _seed_canonical_memories_into_isolated_home(self, codex_home: Path) -> str:
        """Expose the canonical Mente memory store inside the private Codex home."""
        canonical_memories = get_mente_home() / "memories"
        canonical_memories.mkdir(parents=True, exist_ok=True)

        target_memories = codex_home / "memories"
        return self._link_runtime_path_to_canonical_dir(
            codex_home=codex_home,
            runtime_path=target_memories,
            canonical_target=canonical_memories,
            backup_stem="memories.legacy",
        )

    def _seed_canonical_memory_aliases_into_isolated_home(self, codex_home: Path) -> None:
        """Expose compatibility aliases for model-written ~/.mente memory paths."""
        canonical_memories = get_mente_home() / "memories"
        canonical_memories.mkdir(parents=True, exist_ok=True)

        for relative_path, backup_stem in (
            (Path(".mente") / "memories", "dot-mente-memories.legacy"),
            (Path(".mente") / "memory", "dot-mente-memory.legacy"),
        ):
            self._link_runtime_path_to_canonical_dir(
                codex_home=codex_home,
                runtime_path=codex_home / relative_path,
                canonical_target=canonical_memories,
                backup_stem=backup_stem,
            )

    def _link_runtime_path_to_canonical_dir(
        self,
        *,
        codex_home: Path,
        runtime_path: Path,
        canonical_target: Path,
        backup_stem: str,
    ) -> str:
        """Link a runtime path to a canonical directory, preserving legacy contents."""
        try:
            if runtime_path.exists() and runtime_path.resolve() == canonical_target.resolve():
                return "canonical"
            if runtime_path.is_symlink() and runtime_path.resolve() == canonical_target.resolve():
                return "symlink"
        except OSError:
            pass

        if runtime_path.exists() or runtime_path.is_symlink():
            if (
                runtime_path.is_dir()
                and not runtime_path.is_symlink()
                and not any(runtime_path.iterdir())
            ):
                shutil.rmtree(runtime_path)
            else:
                backup_path = self._next_runtime_backup_path(codex_home, backup_stem)
                shutil.move(str(runtime_path), str(backup_path))

        runtime_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            runtime_path.symlink_to(canonical_target, target_is_directory=True)
            return "symlink"
        except OSError as exc:
            raise RuntimeError(
                "failed to expose canonical Mente memories inside private Codex runtime: "
                f"{runtime_path} -> {canonical_target}"
            ) from exc

    def _next_runtime_backup_path(self, codex_home: Path, stem: str) -> Path:
        """Return a non-existing backup path under the runtime home."""
        for _attempt in range(100):
            candidate = codex_home / f"{stem}-{uuid4().hex[:12]}"
            if not candidate.exists():
                return candidate
        return codex_home / f"{stem}-{uuid4().hex}"

    def _seed_user_skills_into_isolated_home(self, codex_home: Path) -> str:
        """Remove legacy private skill mirrors; Codex reads MENTE_SKILLS_DIR directly."""
        canonical_skills = get_skills_dir()
        removed = False
        for target_skills in (
            codex_home / ".agents" / "skills",
            codex_home / ".mente" / "skills",
        ):
            if target_skills.exists() or target_skills.is_symlink():
                self._remove_runtime_path(target_skills)
                removed = True
        if canonical_skills.is_dir():
            return "removed_private_mirror" if removed else "canonical_env"
        return "missing"

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

    def _resolve_sandbox(self, runtime_config: RuntimeConfig) -> str:
        if isinstance(self.sandbox, str) and self.sandbox.strip():
            return self.sandbox.strip()
        if isinstance(runtime_config.sandbox, str) and runtime_config.sandbox.strip():
            return runtime_config.sandbox.strip()
        return self._DEFAULT_SANDBOX

    def _resolve_approval_policy(self, runtime_config: RuntimeConfig) -> str:
        if isinstance(self.approval_policy, str) and self.approval_policy.strip():
            return self.approval_policy.strip()
        if isinstance(runtime_config.approval_policy, str) and runtime_config.approval_policy.strip():
            return runtime_config.approval_policy.strip()
        return self._DEFAULT_APPROVAL_POLICY

    @contextmanager
    def _prepare_runtime_config_for_execution(self, runtime_config: RuntimeConfig):
        model_runtime = runtime_config.model_runtime
        if not model_runtime.requires_responses_compat_proxy:
            yield runtime_config
            return
        api_key = runtime_config.subprocess_env.get("MENTE_CODEX_API_KEY")
        if not api_key:
            raise ResponsesCompatBridgeError("missing_api_key_for_responses_compat_bridge")
        with start_responses_compat_bridge(
            model_runtime=model_runtime,
            api_key=api_key,
        ) as bridge_base_url:
            yield apply_responses_compat_bridge(
                runtime_config,
                bridge_base_url=bridge_base_url,
            )

    def _responses_compat_bridge_failure_result(
        self,
        runtime_config: RuntimeConfig,
        error: Exception,
    ) -> ExecutionResult:
        model_runtime = runtime_config.model_runtime
        summary = self._format_responses_compat_bridge_failure_summary(model_runtime, error)
        return ExecutionResult(
            status="failed",
            summary=summary,
            failure_reason=f"responses_compat_bridge_error:{model_runtime.api_mode}",
            metadata={
                "model_runtime": model_runtime.to_metadata(),
                "bridge_error": str(error),
            },
        )

    def _format_responses_compat_bridge_failure_summary(
        self,
        model_runtime: ModelRuntime,
        error: Exception,
    ) -> str:
        provider = model_runtime.provider or "custom"
        endpoint = model_runtime.base_url or "(missing base_url)"
        model_name = model_runtime.model or "(missing model)"
        return (
            "Mente 的 Responses 兼容桥启动或转发失败："
            f"检测到 model={model_name}、provider={provider}、api_mode={model_runtime.api_mode}、base_url={endpoint}。"
            f"错误={type(error).__name__}: {error}。"
        )

    def _translate_kernel_result(
        self,
        result: KernelExecutionResult,
        request: ExecutionRequest,
        session_request: KernelSessionRequest,
        *,
        model_name: str | None = None,
        precondition_fallback_reason: str | None = None,
        runtime_fallback_reason: str | None = None,
    ) -> ExecutionResult:
        """Translate the vendored kernel result back into the Mente executor contract."""
        translated = ExecutionResult(
            status=result.status,
            summary=(
                normalize_user_facing_summary(
                    result.assistant_summary,
                    user_request=request.user_request,
                    model_name=model_name,
                )
                if result.status == "success"
                else normalize_user_facing_failure_summary(
                    result.assistant_summary,
                    failure_reason=result.backend_failure,
                    user_request=request.user_request,
                )
            ),
            commands_run=list(result.commands_run),
            changed_files=list(result.changed_files),
            artifacts_out=list(result.artifacts_out),
            verification_results=list(result.verification_results),
            follow_up_tasks=list(result.follow_up_tasks),
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
        if self._is_deep_research_request(request):
            self._apply_deep_research_managed_cli_contract(
                translated,
                request=request,
                kernel_result=result,
            )
            self._apply_deep_research_artifact_contract(
                translated,
                request=request,
                kernel_result=result,
            )
        return translated

    def _is_deep_research_request(self, request: ExecutionRequest) -> bool:
        return (
            str(request.metadata.get("task_profile") or "").strip().lower()
            == _DEEP_RESEARCH_TASK_PROFILE
        )

    def _is_skill_audit_request(self, request: ExecutionRequest) -> bool:
        return (
            str(request.metadata.get("task_profile") or "").strip().lower()
            == _SKILL_AUDIT_TASK_PROFILE
        )

    def _apply_deep_research_artifact_contract(
        self,
        translated: ExecutionResult,
        *,
        request: ExecutionRequest,
        kernel_result: KernelExecutionResult,
    ) -> None:
        if translated.status != "success":
            return

        candidate_artifacts = self._collect_deep_research_artifact_candidates(
            request=request,
            kernel_result=kernel_result,
        )
        validated_artifacts, missing_formats, missing_paths = self._validate_deep_research_artifacts(
            candidate_artifacts
        )
        translated.metadata["deep_research_artifact_validation"] = {
            "validated": not missing_formats,
            "missing_formats": missing_formats,
            "missing_paths": missing_paths,
            "candidate_artifacts": candidate_artifacts,
        }
        if missing_formats:
            translated.status = "blocked"
            translated.failure_reason = "deep_research_artifacts_missing"
            translated.artifacts_out = validated_artifacts
            translated.summary = self._format_deep_research_artifact_blocked_summary(
                missing_formats=missing_formats,
                missing_paths=missing_paths,
            )
            return
        translated.artifacts_out = validated_artifacts

    def _collect_deep_research_artifact_candidates(
        self,
        *,
        request: ExecutionRequest,
        kernel_result: KernelExecutionResult,
    ) -> list[str]:
        candidates: list[str] = []
        seen: set[str] = set()

        def _record(raw_path: str) -> None:
            normalized = self._normalize_artifact_path(raw_path, workspace=request.workspace)
            if not normalized or normalized in seen:
                return
            seen.add(normalized)
            candidates.append(normalized)

        for item in kernel_result.artifacts_out:
            _record(str(item))

        structured_output = kernel_result.debug.get("structured_output")
        if isinstance(structured_output, dict):
            for item in structured_output.get("artifacts_out") or []:
                _record(str(item))
            for key in ("assistant_summary", "summary", "final_reply"):
                for path in self._extract_artifact_paths_from_text(structured_output.get(key)):
                    _record(path)

        for path in self._extract_artifact_paths_from_text(kernel_result.assistant_summary):
            _record(path)
        return candidates

    def _normalize_artifact_path(self, raw_path: str, *, workspace: str) -> str | None:
        candidate = str(raw_path or "").strip()
        if not candidate:
            return None
        path = Path(os.path.expandvars(candidate)).expanduser()
        if not path.is_absolute():
            path = Path(workspace).expanduser() / path
        return str(path.resolve())

    def _extract_artifact_paths_from_text(self, text: Any) -> list[str]:
        raw_text = str(text or "")
        if not raw_text:
            return []
        extracted: list[str] = []
        seen: set[str] = set()
        for match in _ARTIFACT_PATH_PATTERN.finditer(raw_text):
            candidate = match.group("path").rstrip(_ARTIFACT_PATH_TRAILING_PUNCTUATION)
            if not candidate or candidate in seen:
                continue
            seen.add(candidate)
            extracted.append(candidate)
        return extracted

    def _validate_deep_research_artifacts(
        self,
        candidate_artifacts: list[str],
    ) -> tuple[list[str], list[str], list[str]]:
        validated: list[str] = []
        existing_by_suffix: dict[str, str] = {}
        missing_paths: list[str] = []
        seen_existing: set[str] = set()
        for candidate in candidate_artifacts:
            path = Path(candidate)
            if not path.exists():
                missing_paths.append(candidate)
                continue
            if candidate not in seen_existing:
                seen_existing.add(candidate)
                validated.append(candidate)
            suffix = path.suffix.lower()
            if suffix == ".markdown":
                suffix = ".md"
            if suffix in _DEEP_RESEARCH_REQUIRED_ARTIFACT_SUFFIXES and suffix not in existing_by_suffix:
                existing_by_suffix[suffix] = candidate
        missing_formats = sorted(
            suffix
            for suffix in _DEEP_RESEARCH_REQUIRED_ARTIFACT_SUFFIXES
            if suffix not in existing_by_suffix
        )
        ordered_validated = [
            existing_by_suffix[suffix]
            for suffix in _DEEP_RESEARCH_REQUIRED_ARTIFACT_SUFFIXES
            if suffix in existing_by_suffix
        ]
        for candidate in validated:
            if candidate not in ordered_validated:
                ordered_validated.append(candidate)
        return ordered_validated, missing_formats, missing_paths

    def _format_deep_research_artifact_blocked_summary(
        self,
        *,
        missing_formats: list[str],
        missing_paths: list[str],
    ) -> str:
        format_labels = {
            ".md": "Markdown (.md)",
            ".html": "HTML (.html)",
            ".docx": "DOCX (.docx)",
        }
        missing_format_text = "、".join(format_labels.get(item, item) for item in missing_formats)
        summary = (
            "深度研究任务未产出完整报告工件："
            f"缺少 {missing_format_text} 的实际文件，当前结果不能判定为完成。"
            "请继续执行深度研究工作流，并返回已生成的 Markdown、HTML、DOCX 文件路径。"
        )
        if missing_paths:
            preview = "；".join(missing_paths[:3])
            summary += f" 未落盘的候选路径：{preview}"
        return summary

    def _should_execute_managed_deep_research_directly(self, request: ExecutionRequest) -> bool:
        if not self._is_deep_research_request(request):
            return False
        return self._resolve_deep_research_skill_entrypoint(request).exists()

    def _execute_managed_deep_research_directly(
        self,
        request: ExecutionRequest,
        *,
        runtime_config: RuntimeConfig,
    ) -> ExecutionResult:
        command = self._build_deep_research_managed_cli_argv(request)
        emit_execution_event(
            self._event_callback,
            "executor.managed_skill.started",
            {
                "task_id": request.task_id,
                "session_id": request.session_id,
                "skill": "research/deep-research-pro",
                "mode": "direct_subprocess",
                "command": command,
            },
            logger=logger,
        )
        completed = subprocess.run(
            command,
            cwd=request.workspace,
            env=self._build_managed_deep_research_subprocess_env(runtime_config),
            capture_output=True,
            text=True,
        )
        stdout = str(completed.stdout or "")
        stderr = str(completed.stderr or "")
        candidate_artifacts = self._collect_deep_research_artifact_candidates_from_texts(
            request=request,
            texts=[stdout, stderr],
        )
        validated_artifacts, missing_formats, missing_paths = self._validate_deep_research_artifacts(
            candidate_artifacts
        )

        if completed.returncode == 0 and not missing_formats:
            status = "success"
            failure_reason = None
            summary = self._format_managed_deep_research_direct_success_summary(validated_artifacts)
            verification_results = [
                "managed deep-research CLI exited successfully",
                "checked report files exist",
            ]
        elif completed.returncode != 0:
            status = "blocked"
            failure_reason = "deep_research_managed_cli_failed"
            summary = self._format_managed_deep_research_direct_failure_summary(
                returncode=completed.returncode,
                stdout=stdout,
                stderr=stderr,
                artifacts=validated_artifacts,
            )
            verification_results = []
        else:
            status = "blocked"
            failure_reason = "deep_research_artifacts_missing"
            summary = self._format_deep_research_artifact_blocked_summary(
                missing_formats=missing_formats,
                missing_paths=missing_paths,
            )
            verification_results = []

        result = ExecutionResult(
            status=status,
            summary=summary,
            commands_run=[shlex.join(command)],
            artifacts_out=validated_artifacts,
            verification_results=verification_results,
            failure_reason=failure_reason,
            metadata={
                "managed_skill_execution": {
                    "mode": "direct_subprocess",
                    "command": list(command),
                    "returncode": completed.returncode,
                },
                "managed_skill_stdout": stdout,
                "managed_skill_stderr": stderr,
                "deep_research_artifact_validation": {
                    "validated": not missing_formats,
                    "missing_formats": missing_formats,
                    "missing_paths": missing_paths,
                    "candidate_artifacts": candidate_artifacts,
                },
            },
        )
        stateless_session = KernelSessionRequest(mode=KernelSessionMode.STATELESS)
        result.metadata["execution_session"] = self._execution_session_metadata(
            request,
            stateless_session,
            result,
        )
        emit_execution_event(
            self._event_callback,
            "executor.managed_skill.completed",
            {
                "task_id": request.task_id,
                "session_id": request.session_id,
                "skill": "research/deep-research-pro",
                "mode": "direct_subprocess",
                "returncode": completed.returncode,
                "status": result.status,
            },
            logger=logger,
        )
        return result

    def _build_managed_deep_research_subprocess_env(
        self,
        runtime_config: RuntimeConfig,
    ) -> dict[str, str]:
        env = build_private_runtime_env(runtime_config.runtime_home, runtime_config.subprocess_env)
        mente_home = get_mente_home().expanduser().resolve()
        env["HOME"] = str(mente_home.parent)
        env["MENTE_HOME"] = str(mente_home)
        env["HERMES_HOME"] = str(mente_home)
        env.setdefault("PYTHONIOENCODING", "utf-8")
        for key, value in self._load_env_file_values(mente_home / ".env").items():
            env.setdefault(key, value)
        return env

    def _load_env_file_values(self, env_path: Path) -> dict[str, str]:
        if not env_path.exists():
            return {}
        values: dict[str, str] = {}
        try:
            lines = env_path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return {}
        for raw_line in lines:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            normalized_key = key.strip()
            normalized_value = value.strip().strip("\"'")
            if normalized_key:
                values[normalized_key] = normalized_value
        return values

    def _collect_deep_research_artifact_candidates_from_texts(
        self,
        *,
        request: ExecutionRequest,
        texts: list[str],
    ) -> list[str]:
        candidates: list[str] = []
        seen: set[str] = set()
        for text in texts:
            for raw_path in self._extract_artifact_paths_from_text(text):
                normalized = self._normalize_artifact_path(raw_path, workspace=request.workspace)
                if not normalized or normalized in seen:
                    continue
                seen.add(normalized)
                candidates.append(normalized)
        return candidates

    def _format_managed_deep_research_direct_success_summary(self, artifacts: list[str]) -> str:
        if not artifacts:
            return "深度研究完成。"
        labels = {
            ".md": "Markdown",
            ".html": "HTML",
            ".docx": "DOCX",
        }
        lines = ["深度研究完成。"]
        for artifact in artifacts:
            suffix = Path(artifact).suffix.lower()
            label = labels.get(suffix, "Artifact")
            lines.append(f"{label}: {artifact}")
        return "\n".join(lines)

    def _format_managed_deep_research_direct_failure_summary(
        self,
        *,
        returncode: int,
        stdout: str,
        stderr: str,
        artifacts: list[str],
    ) -> str:
        lines = [f"托管 deep-research CLI 执行失败，退出码 {returncode}。"]
        detail = stderr.strip() or stdout.strip()
        if detail:
            lines.append(detail)
        if artifacts:
            lines.append("已生成的工件：")
            lines.extend(artifacts)
        return "\n".join(lines)

    def _maybe_retry_deep_research_after_incomplete_turn(
        self,
        *,
        request: ExecutionRequest,
        session_request: KernelSessionRequest,
        kernel_result: KernelExecutionResult,
        runtime_config: RuntimeConfig,
    ) -> tuple[KernelExecutionResult, KernelSessionRequest, ExecutionRequest, dict[str, Any]] | None:
        if not self._is_deep_research_request(request):
            return None
        validation = self._deep_research_managed_cli_validation(
            request=request,
            kernel_result=kernel_result,
        )
        thread_id = validation["thread_id"]
        if session_request.mode is not KernelSessionMode.SESSION or not thread_id:
            return None
        if validation["active_managed_cli_commands"] and not self._deep_research_retry_reason_attempted(
            request,
            "managed_cli_still_running",
        ):
            retry_request = self._build_deep_research_cli_retry_request(
                request,
                reason="managed_cli_still_running",
                active_commands=validation["active_managed_cli_commands"],
            )
            retry_session = KernelSessionRequest(
                mode=KernelSessionMode.SESSION,
                session_id=thread_id,
            )
            retry_result = self._runner.run(
                payload=self._build_kernel_payload(retry_request),
                session=retry_session,
                runtime_config=runtime_config,
            )
            return (
                retry_result,
                retry_session,
                retry_request,
                {
                    "triggered": True,
                    "reason": "managed_cli_still_running",
                    "resumed_thread_id": thread_id,
                },
            )
        if validation["executed"] or not validation["deferred_execution"]:
            return None
        if self._deep_research_retry_reason_attempted(request, "managed_cli_not_executed"):
            return None
        retry_request = self._build_deep_research_cli_retry_request(
            request,
            reason="managed_cli_not_executed",
        )
        retry_session = KernelSessionRequest(
            mode=KernelSessionMode.SESSION,
            session_id=thread_id,
        )
        retry_result = self._runner.run(
            payload=self._build_kernel_payload(retry_request),
            session=retry_session,
            runtime_config=runtime_config,
        )
        return (
            retry_result,
            retry_session,
            retry_request,
            {
                "triggered": True,
                "reason": "managed_cli_not_executed",
                "resumed_thread_id": thread_id,
            },
        )

    def _maybe_retry_skill_audit_after_incomplete_turn(
        self,
        *,
        request: ExecutionRequest,
        session_request: KernelSessionRequest,
        kernel_result: KernelExecutionResult,
        runtime_config: RuntimeConfig,
    ) -> tuple[KernelExecutionResult, KernelSessionRequest, ExecutionRequest, dict[str, Any]] | None:
        if not self._is_skill_audit_request(request):
            return None
        validation = self._skill_audit_probe_only_validation(kernel_result=kernel_result)
        thread_id = validation["thread_id"]
        if session_request.mode is not KernelSessionMode.SESSION or not thread_id:
            return None
        if not validation["probe_only_turn"] or self._skill_audit_retry_attempted(request):
            return None
        retry_request = self._build_skill_audit_retry_request(request)
        retry_session = KernelSessionRequest(
            mode=KernelSessionMode.SESSION,
            session_id=thread_id,
        )
        retry_result = self._runner.run(
            payload=self._build_kernel_payload(retry_request),
            session=retry_session,
            runtime_config=runtime_config,
        )
        return (
            retry_result,
            retry_session,
            retry_request,
            {
                "triggered": True,
                "reason": "probe_only_turn",
                "resumed_thread_id": thread_id,
            },
        )

    def _build_skill_audit_retry_request(self, request: ExecutionRequest) -> ExecutionRequest:
        retry_fact = "\n".join(
            [
                "Skill audit retry instruction:",
                "- The previous turn stopped after only reading the skill instructions or locating entry scripts.",
                "- Do not stop at process narration, a next-step update, or a summary of what you plan to inspect.",
                "- Continue the same session and finish the audit now.",
                "- Read only the remaining directly relevant skill files you actually need, then return concrete optimization findings with file references.",
                "- If a targeted review is still blocked after those reads, set completion_status to blocked and explain the concrete blocker.",
            ]
        )
        memory_facts = list(request.memory_facts)
        if retry_fact not in memory_facts:
            memory_facts.append(retry_fact)
        metadata = dict(request.metadata)
        metadata["skill_audit_retry_attempted"] = True
        return request.model_copy(
            update={
                "memory_facts": memory_facts,
                "metadata": metadata,
            }
        )

    def _skill_audit_probe_only_validation(
        self,
        *,
        kernel_result: KernelExecutionResult,
    ) -> dict[str, Any]:
        command_state = self._extract_command_execution_state(
            kernel_result.debug.get("stdout"),
        )
        commands_seen = command_state["commands_seen"]
        text = "\n".join(
            [
                str(kernel_result.assistant_summary or "").strip(),
                *[str(item).strip() for item in kernel_result.follow_up_tasks],
            ]
        )
        read_only_probe = bool(commands_seen) and all(
            self._looks_like_read_only_probe_command(command) for command in commands_seen
        )
        probe_only_turn = read_only_probe and any(
            pattern.search(text) for pattern in _SKILL_AUDIT_PROBE_ONLY_PATTERNS
        )
        return {
            "probe_only_turn": probe_only_turn,
            "commands_seen": commands_seen,
            "active_commands": command_state["active_commands"],
            "thread_id": self._extract_kernel_thread_id(kernel_result),
        }

    def _skill_audit_retry_attempted(self, request: ExecutionRequest) -> bool:
        metadata = request.metadata if isinstance(request.metadata, dict) else {}
        return bool(metadata.get("skill_audit_retry_attempted"))

    def _build_deep_research_cli_retry_request(
        self,
        request: ExecutionRequest,
        *,
        reason: str,
        active_commands: list[str] | None = None,
    ) -> ExecutionRequest:
        retry_fact = self._build_deep_research_cli_retry_fact(
            request,
            reason=reason,
            active_commands=active_commands or [],
        )
        memory_facts = list(request.memory_facts)
        if retry_fact not in memory_facts:
            memory_facts.append(retry_fact)
        metadata = dict(request.metadata)
        metadata["deep_research_cli_retry_attempted"] = True
        reasons_attempted = self._normalize_deep_research_retry_reasons(metadata)
        if reason not in reasons_attempted:
            reasons_attempted.append(reason)
        metadata["deep_research_cli_retry_reasons_attempted"] = reasons_attempted
        return request.model_copy(
            update={
                "memory_facts": memory_facts,
                "metadata": metadata,
            }
        )

    def _build_deep_research_cli_retry_fact(
        self,
        request: ExecutionRequest,
        *,
        reason: str,
        active_commands: list[str],
    ) -> str:
        launch_command = self._build_deep_research_managed_cli_launch_command(request)
        if reason == "managed_cli_still_running":
            retry_lines = [
                "Deep research retry instruction:",
                "- The previous turn already launched the managed deep-research CLI.",
                "- Do not stop while the managed CLI command is still running.",
                "- Resume the same session, wait for the active CLI command to finish, and only then verify the output directory.",
                "- Confirm that Markdown, HTML, and DOCX report artifacts exist before you conclude the task.",
                "- Only report blocked if the CLI exits with a concrete error or the required artifacts are still missing after verification.",
            ]
            if active_commands:
                retry_lines.append(f"- Active CLI command: {active_commands[0]}")
            return "\n".join(retry_lines)
        return "\n".join(
            [
                "Deep research retry instruction:",
                "- The previous turn stopped after only reading skill files.",
                "- Do not summarize, stop at planning, or ask for confirmation.",
                f"- Execute the managed deep-research CLI now: {launch_command}",
                "- Continue until Markdown, HTML, and DOCX report artifacts exist or a concrete execution blocker is verified after attempting the CLI.",
            ]
        )

    def _deep_research_retry_reason_attempted(
        self,
        request: ExecutionRequest,
        reason: str,
    ) -> bool:
        metadata = request.metadata if isinstance(request.metadata, dict) else {}
        reasons_attempted = self._normalize_deep_research_retry_reasons(metadata)
        if reason in reasons_attempted:
            return True
        return reason == "managed_cli_not_executed" and bool(
            metadata.get("deep_research_cli_retry_attempted")
        )

    def _normalize_deep_research_retry_reasons(self, metadata: dict[str, Any]) -> list[str]:
        raw_reasons = metadata.get("deep_research_cli_retry_reasons_attempted")
        if not isinstance(raw_reasons, list):
            return []
        normalized: list[str] = []
        for value in raw_reasons:
            text = str(value or "").strip()
            if text and text not in normalized:
                normalized.append(text)
        return normalized

    def _build_deep_research_managed_cli_launch_command(self, request: ExecutionRequest) -> str:
        skill_entrypoint = str(self._resolve_deep_research_skill_entrypoint(request))
        product_name = self._infer_deep_research_product_name(request.user_request)
        quoted_product_name = json.dumps(product_name or "<研究对象>", ensure_ascii=False)
        output_root = resolve_deep_research_output_root()
        return f"python {skill_entrypoint} {quoted_product_name} --output-dir {output_root}"

    def _build_deep_research_managed_cli_argv(self, request: ExecutionRequest) -> list[str]:
        return [
            sys.executable,
            str(self._resolve_deep_research_skill_entrypoint(request)),
            self._infer_deep_research_product_name(request.user_request) or "<研究对象>",
            "--output-dir",
            str(resolve_deep_research_output_root()),
        ]

    def _resolve_deep_research_skill_entrypoint(self, request: ExecutionRequest) -> Path:
        operator_capsule = request.metadata.get("operator_capsule")
        if isinstance(operator_capsule, dict):
            raw_entrypoint = operator_capsule.get("skill_entrypoint")
            if raw_entrypoint:
                return Path(str(raw_entrypoint).strip()).expanduser()
        return get_skills_dir() / "research" / "deep-research-pro" / "deep_research_pro.py"

    def _infer_deep_research_product_name(self, user_request: str | None) -> str | None:
        text = str(user_request or "").strip()
        if not text:
            return None
        normalized = re.sub(r"^\s*调用(?:深度研究)?技能[，,\s]*", "", text)
        match = re.search(r"(?:深度研究|深度调研)(?:一下|下)?(?P<subject>.+)", normalized, re.IGNORECASE)
        candidate = match.group("subject") if match else normalized
        candidate = candidate.strip(" ：:，,。.!！?？\"'")
        candidate = re.sub(r"这一个标准化学品.*$", "", candidate)
        candidate = re.sub(r"(?:并|并且)?(?:输出|形成|生成|撰写|整理|做成).*$", "", candidate)
        candidate = re.sub(r"(?:完整|万字)?调研报告.*$", "", candidate)
        candidate = re.sub(r"(?:完整)?报告.*$", "", candidate)
        candidate = candidate.strip(" ：:，,。.!！?？\"'")
        return candidate or None

    def _apply_deep_research_managed_cli_contract(
        self,
        translated: ExecutionResult,
        *,
        request: ExecutionRequest,
        kernel_result: KernelExecutionResult,
    ) -> None:
        validation = self._deep_research_managed_cli_validation(
            request=request,
            kernel_result=kernel_result,
        )
        if validation["executed"] or not validation["deferred_execution"]:
            return
        translated.status = "blocked"
        translated.failure_reason = "deep_research_managed_cli_not_executed"
        translated.summary = self._format_deep_research_managed_cli_not_executed_summary(
            commands_seen=validation["commands_seen"],
        )
        translated.metadata["deep_research_managed_cli_validation"] = validation

    def _deep_research_managed_cli_validation(
        self,
        *,
        request: ExecutionRequest,
        kernel_result: KernelExecutionResult,
    ) -> dict[str, Any]:
        command_state = self._extract_command_execution_state(
            kernel_result.debug.get("stdout"),
        )
        commands_seen = command_state["commands_seen"]
        active_commands = command_state["active_commands"]
        managed_cli_commands = self._extract_managed_deep_research_cli_commands(
            request=request,
            commands_seen=commands_seen,
        )
        active_managed_cli_commands = self._extract_managed_deep_research_cli_commands(
            request=request,
            commands_seen=active_commands,
        )
        executed = self._managed_deep_research_cli_was_executed(
            request=request,
            commands_seen=commands_seen,
        )
        return {
            "executed": executed,
            "managed_cli_commands": managed_cli_commands,
            "active_commands": active_commands,
            "active_managed_cli_commands": active_managed_cli_commands,
            "deferred_execution": self._looks_like_deep_research_deferred_execution(
                assistant_summary=kernel_result.assistant_summary,
                follow_up_tasks=kernel_result.follow_up_tasks,
                commands_seen=commands_seen,
                managed_cli_executed=executed,
            ),
            "commands_seen": commands_seen,
            "thread_id": self._extract_deep_research_thread_id(kernel_result),
        }

    def _extract_command_execution_state(self, stdout: Any) -> dict[str, list[str]]:
        raw_stdout = str(stdout or "")
        if not raw_stdout:
            return {"commands_seen": [], "active_commands": []}
        commands: list[str] = []
        seen: set[str] = set()
        active_by_item_id: dict[str, str] = {}
        for line in raw_stdout.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            try:
                payload = json.loads(stripped)
            except json.JSONDecodeError:
                continue
            event_type = payload.get("type")
            if event_type not in {"item.started", "item.completed"}:
                continue
            item = payload.get("item")
            if not isinstance(item, dict) or item.get("type") != "command_execution":
                continue
            item_id = str(item.get("id") or "").strip()
            command = str(item.get("command") or "").strip()
            if command and command not in seen:
                seen.add(command)
                commands.append(command)
            if not item_id:
                continue
            if event_type == "item.started":
                if command:
                    active_by_item_id[item_id] = command
                continue
            active_by_item_id.pop(item_id, None)
        active_commands: list[str] = []
        for command in active_by_item_id.values():
            if command not in active_commands:
                active_commands.append(command)
        return {
            "commands_seen": commands,
            "active_commands": active_commands,
        }

    def _extract_command_execution_commands(self, stdout: Any) -> list[str]:
        return self._extract_command_execution_state(stdout)["commands_seen"]

    def _extract_managed_deep_research_cli_commands(
        self,
        *,
        request: ExecutionRequest,
        commands_seen: list[str],
    ) -> list[str]:
        managed_commands: list[str] = []
        operator_capsule = request.metadata.get("operator_capsule")
        skill_entrypoint = None
        if isinstance(operator_capsule, dict):
            raw_entrypoint = operator_capsule.get("skill_entrypoint")
            if raw_entrypoint:
                skill_entrypoint = str(raw_entrypoint).strip()
        for command in commands_seen:
            normalized = command.strip().lower()
            if self._looks_like_read_only_deep_research_probe(normalized):
                continue
            if skill_entrypoint and skill_entrypoint in command:
                managed_commands.append(command)
                continue
            if "deep_research_pro.py" in command:
                managed_commands.append(command)
        return managed_commands

    def _managed_deep_research_cli_was_executed(
        self,
        *,
        request: ExecutionRequest,
        commands_seen: list[str],
    ) -> bool:
        return bool(
            self._extract_managed_deep_research_cli_commands(
                request=request,
                commands_seen=commands_seen,
            )
        )

    def _looks_like_read_only_deep_research_probe(self, command: str) -> bool:
        return self._looks_like_read_only_probe_command(
            command,
            prefixes=_DEEP_RESEARCH_READ_ONLY_COMMAND_PREFIXES,
        )

    def _looks_like_deep_research_deferred_execution(
        self,
        *,
        assistant_summary: str,
        follow_up_tasks: list[str],
        commands_seen: list[str],
        managed_cli_executed: bool,
    ) -> bool:
        text = "\n".join(
            [str(assistant_summary or "").strip(), *[str(item).strip() for item in follow_up_tasks]]
        )
        if (
            not managed_cli_executed
            and commands_seen
            and all(self._looks_like_read_only_deep_research_probe(command) for command in commands_seen)
        ):
            return True
        if not text.strip():
            return False
        return any(pattern.search(text) for pattern in _DEEP_RESEARCH_DEFERRED_EXECUTION_PATTERNS)

    def _extract_kernel_thread_id(self, kernel_result: KernelExecutionResult) -> str | None:
        thread_id = str(kernel_result.debug.get("thread_id") or "").strip()
        if thread_id:
            return thread_id
        stdout = str(kernel_result.debug.get("stdout") or "")
        match = re.search(r'"thread_id"\s*:\s*"([^"]+)"', stdout)
        if match:
            return match.group(1).strip() or None
        return None

    def _extract_deep_research_thread_id(self, kernel_result: KernelExecutionResult) -> str | None:
        return self._extract_kernel_thread_id(kernel_result)

    def _looks_like_read_only_probe_command(
        self,
        command: str,
        *,
        prefixes: tuple[str, ...] = _DEEP_RESEARCH_READ_ONLY_COMMAND_PREFIXES,
    ) -> bool:
        normalized = command.strip().lower()
        if normalized.startswith("/bin/bash -lc "):
            normalized = normalized[len("/bin/bash -lc ") :].strip("\"'")
        return normalized.startswith(prefixes)

    def _format_deep_research_managed_cli_not_executed_summary(
        self,
        *,
        commands_seen: list[str],
    ) -> str:
        summary = (
            "深度研究任务本回合未真正执行托管 deep-research CLI，"
            "只停留在读取技能入口或说明文件的探测阶段，因此当前结果不能判定为有效进展。"
            "请直接执行托管 CLI 工作流，并继续产出 Markdown、HTML、DOCX 报告工件。"
        )
        if commands_seen:
            summary += f" 本回合命令：{'；'.join(commands_seen[:3])}"
        return summary
