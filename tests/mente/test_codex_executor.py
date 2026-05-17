import json
import os
import subprocess
from contextlib import contextmanager
from pathlib import Path

import pytest

from hermes_cli.auth import AuthError
from kernel.codex.runtime.launcher import build_private_runtime_env, build_stateless_command
from kernel.codex.runtime.protocol import KernelExecutionPayload
from kernel.codex.runtime.result import KernelExecutionResult
from kernel.codex.runtime.runner import KernelRunner
from kernel.codex.session.protocol import KernelSessionMode, KernelSessionRequest
from mente.executors import CodexKernelAdapter, ToolExposurePolicy, resolve_runtime_home
from mente.executors.base import Executor
from mente.executors.prompting import (
    build_prompt_fingerprint,
    normalize_user_facing_summary,
    render_execution_prompt,
)
from mente.executors.runtime_config import (
    MENTE_CONTENT_BASE_INSTRUCTIONS,
    MENTE_DEFAULT_AUTO_COMPACT_TOKEN_LIMIT,
    ModelRuntime,
    RuntimeConfig,
)
from mente.executors.codex import CodexExecutor
from mente.feature_flags import sessionful_execution_sources
from mente.memory.models import MemoryRecord
from mente.memory.repository import InMemoryMemoryRepository
from mente.task_core.models import (
    ExecutionMode,
    ExecutionRequest,
    ExecutionSession,
    SessionMode,
)


@pytest.fixture(autouse=True)
def _stub_runtime_auth_resolution(monkeypatch):
    monkeypatch.setattr(
        "mente.executors.runtime_auth.resolve_codex_runtime_credentials",
        lambda **kwargs: {"api_key": "stub-private-access-token"},
    )


def _build_adapter_payload(adapter: CodexKernelAdapter, request: ExecutionRequest) -> dict[str, object]:
    """Exercise the adapter seam without importing CLI-specific details."""
    return adapter.build_request_payload(request)


def _agent_runtime_home(mente_home: Path, agent_id: str) -> Path:
    return mente_home / "runtime" / "agents" / agent_id / "codex"


def test_codex_kernel_adapter_contract_exists():
    assert issubclass(CodexKernelAdapter, Executor)


def test_codex_executor_implements_kernel_adapter_contract():
    executor = CodexExecutor(codex_binary="codex")
    request = ExecutionRequest(
        task_id="task_1",
        session_id="session_1",
        task_type="engineering",
        objective="Inspect repository",
        user_request="inspect repository",
        workspace=".",
    )

    payload = _build_adapter_payload(executor, request)

    assert isinstance(executor, CodexKernelAdapter)
    assert executor.supports_kernel_sessions() is False
    assert payload["prompt"] == render_execution_prompt(request)
    assert payload["workspace"] == request.workspace
    assert "command" not in payload
    assert "argv" not in payload
    assert "schema_path" not in payload


def test_codex_executor_adapter_payload_stays_stateless():
    executor = CodexExecutor(codex_binary="codex")
    request = ExecutionRequest(
        task_id="task_1",
        session_id="session_1",
        task_type="engineering",
        objective="Inspect repository",
        user_request="inspect repository",
        workspace=".",
        resume_token="resume-123",
    )

    payload = executor.build_request_payload(request)

    assert executor.supports_kernel_sessions() is False
    assert "session_id" not in payload
    assert "resume_token" not in payload


def test_codex_executor_sessionful_opt_in_is_disabled_by_default(monkeypatch, tmp_path):
    monkeypatch.delenv("MENTE_SESSIONFUL_EXECUTION_ENABLED", raising=False)
    captured: dict[str, object] = {}

    class _Runner:
        def run(self, *, payload, session, runtime_config):
            captured["session"] = session
            return KernelExecutionResult(status="success", assistant_summary="ok")

    executor = CodexExecutor(codex_binary="codex", runner=_Runner())
    request = ExecutionRequest(
        task_id="task_1",
        session_id="session_1",
        task_type="conversation",
        objective="Reply",
        user_request="Reply to the user",
        workspace=str(tmp_path),
        execution_mode=ExecutionMode.SESSIONFUL,
        execution_session=ExecutionSession(mode=SessionMode.START),
        tool_policy={
            "session_capable": True,
            "bridge_tools": ["mente_memory_query"],
        },
        metadata={"source": "api_server"},
    )

    result = executor.execute(request)

    assert result.status == "success"
    assert captured["session"].mode is KernelSessionMode.STATELESS
    assert result.metadata["execution_session"] == {
        "mode": "stateless",
        "requested_mode": "start",
        "effective_mode": "stateless",
        "source": "api_server",
        "session_capable": True,
        "continuity_id": None,
        "continuity_status": "fallback_stateless",
        "fallback_reason": "feature_flag_disabled",
    }


def test_codex_executor_passes_sessionful_resume_intent_to_kernel_seam_when_enabled(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("MENTE_SESSIONFUL_EXECUTION_ENABLED", "1")
    captured: dict[str, object] = {}

    class _Runner:
        def run(self, *, payload, session, runtime_config):
            captured["session"] = session
            return KernelExecutionResult(
                status="success",
                assistant_summary="ok",
                debug={"thread_id": "thread-123"},
            )

    executor = CodexExecutor(codex_binary="codex", runner=_Runner())
    request = ExecutionRequest(
        task_id="task_1",
        session_id="session_1",
        task_type="conversation",
        objective="Reply",
        user_request="Reply to the user",
        workspace=str(tmp_path),
        execution_mode=ExecutionMode.SESSIONFUL,
        execution_session=ExecutionSession(
            mode=SessionMode.RESUME,
            continuity_id="thread-123",
        ),
        tool_policy={"session_capable": True},
        metadata={"source": "api_server"},
    )

    result = executor.execute(request)

    assert captured["session"].mode is KernelSessionMode.SESSION
    assert captured["session"].session_id == "thread-123"
    assert result.metadata["execution_session"] == {
        "mode": "resume",
        "requested_mode": "resume",
        "effective_mode": "resume",
        "source": "api_server",
        "session_capable": True,
        "continuity_id": "thread-123",
        "continuity_status": "resumed",
        "fallback_reason": None,
    }


def test_codex_executor_allows_gateway_sessionful_resume_when_source_is_allowlisted(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("MENTE_SESSIONFUL_EXECUTION_ENABLED", "1")
    monkeypatch.setenv("MENTE_SESSIONFUL_EXECUTION_SOURCES", "api_server,gateway")
    captured: dict[str, object] = {}

    class _Runner:
        def run(self, *, payload, session, runtime_config):
            captured["session"] = session
            return KernelExecutionResult(
                status="success",
                assistant_summary="ok",
                debug={"thread_id": "thread-456"},
            )

    executor = CodexExecutor(codex_binary="codex", runner=_Runner())
    request = ExecutionRequest(
        task_id="task_1",
        session_id="session_1",
        task_type="conversation",
        objective="Reply",
        user_request="Reply to the user",
        workspace=str(tmp_path),
        execution_mode=ExecutionMode.SESSIONFUL,
        execution_session=ExecutionSession(
            mode=SessionMode.RESUME,
            continuity_id="thread-456",
        ),
        tool_policy={"session_capable": True},
        metadata={"source": "gateway"},
    )

    result = executor.execute(request)

    assert captured["session"].mode is KernelSessionMode.SESSION
    assert captured["session"].session_id == "thread-456"
    assert result.metadata["execution_session"]["continuity_status"] == "resumed"
    assert result.metadata["execution_session"]["continuity_id"] == "thread-456"


def test_sessionful_execution_sources_default_to_all_sessionful_entrypoints(monkeypatch):
    monkeypatch.delenv("MENTE_SESSIONFUL_EXECUTION_SOURCES", raising=False)

    assert sessionful_execution_sources() == {
        "api_server",
        "gateway",
        "tui",
        "oneshot",
    }


def test_codex_executor_falls_back_to_stateless_when_resume_fails(monkeypatch, tmp_path):
    monkeypatch.setenv("MENTE_SESSIONFUL_EXECUTION_ENABLED", "1")
    calls: list[KernelSessionRequest] = []

    class _Runner:
        def run(self, *, payload, session, runtime_config):
            calls.append(session)
            if session.mode is KernelSessionMode.SESSION:
                return KernelExecutionResult(
                    status="failed",
                    assistant_summary="thread not found",
                    backend_failure="thread_not_found",
                )
            return KernelExecutionResult(status="success", assistant_summary="stateless fallback")

    executor = CodexExecutor(codex_binary="codex", runner=_Runner())
    request = ExecutionRequest(
        task_id="task_1",
        session_id="session_1",
        task_type="conversation",
        objective="Reply",
        user_request="Reply to the user",
        workspace=str(tmp_path),
        execution_mode=ExecutionMode.SESSIONFUL,
        execution_session=ExecutionSession(
            mode=SessionMode.RESUME,
            continuity_id="thread-stale",
        ),
        tool_policy={"session_capable": True},
        metadata={"source": "api_server"},
    )

    result = executor.execute(request)

    assert [session.mode for session in calls] == [
        KernelSessionMode.SESSION,
        KernelSessionMode.STATELESS,
    ]
    assert result.status == "success"
    assert result.summary == "stateless fallback"
    assert result.metadata["execution_session"] == {
        "mode": "stateless",
        "requested_mode": "resume",
        "effective_mode": "stateless",
        "source": "api_server",
        "session_capable": True,
        "continuity_id": None,
        "continuity_status": "fallback_stateless",
        "fallback_reason": "thread_not_found",
    }


def test_codex_executor_resume_failure_retries_with_fallback_history_fact(monkeypatch, tmp_path):
    monkeypatch.setenv("MENTE_SESSIONFUL_EXECUTION_ENABLED", "1")
    monkeypatch.setenv("MENTE_SESSIONFUL_EXECUTION_SOURCES", "gateway")
    payloads: list[tuple[str, KernelSessionRequest]] = []
    fallback_history_fact = 'Conversation history (JSON):\n[{"role":"user","content":"before"}]'

    class _Runner:
        def run(self, *, payload, session, runtime_config):
            payloads.append((payload.prompt, session))
            if session.mode is KernelSessionMode.SESSION:
                return KernelExecutionResult(
                    status="failed",
                    assistant_summary="thread not found",
                    backend_failure="thread_not_found",
                )
            return KernelExecutionResult(status="success", assistant_summary="fallback ok")

    executor = CodexExecutor(codex_binary="codex", runner=_Runner())
    request = ExecutionRequest(
        task_id="task_1",
        session_id="session_1",
        task_type="conversation",
        objective="Reply",
        user_request="Reply to the user",
        workspace=str(tmp_path),
        execution_mode=ExecutionMode.SESSIONFUL,
        execution_session=ExecutionSession(
            mode=SessionMode.RESUME,
            continuity_id="thread-stale",
        ),
        tool_policy={"session_capable": True},
        metadata={
            "source": "gateway",
            "fallback_history_fact": fallback_history_fact,
        },
    )

    result = executor.execute(request)

    assert result.status == "success"
    assert len(payloads) == 2
    assert payloads[0][1].mode is KernelSessionMode.SESSION
    assert fallback_history_fact not in payloads[0][0]
    assert payloads[1][1].mode is KernelSessionMode.STATELESS
    assert fallback_history_fact in payloads[1][0]


def test_codex_executor_resume_failure_does_not_duplicate_fallback_history(monkeypatch, tmp_path):
    monkeypatch.setenv("MENTE_SESSIONFUL_EXECUTION_ENABLED", "1")
    monkeypatch.setenv("MENTE_SESSIONFUL_EXECUTION_SOURCES", "gateway")
    prompts: list[str] = []
    fallback_history_fact = 'Conversation history (JSON):\n[{"role":"user","content":"before"}]'

    class _Runner:
        def run(self, *, payload, session, runtime_config):
            prompts.append(payload.prompt)
            if session.mode is KernelSessionMode.SESSION:
                return KernelExecutionResult(
                    status="failed",
                    assistant_summary="thread not found",
                    backend_failure="thread_not_found",
                )
            return KernelExecutionResult(status="success", assistant_summary="fallback ok")

    executor = CodexExecutor(codex_binary="codex", runner=_Runner())
    request = ExecutionRequest(
        task_id="task_1",
        session_id="session_1",
        task_type="conversation",
        objective="Reply",
        user_request="Reply to the user",
        workspace=str(tmp_path),
        execution_mode=ExecutionMode.SESSIONFUL,
        execution_session=ExecutionSession(
            mode=SessionMode.RESUME,
            continuity_id="thread-stale",
        ),
        memory_facts=[fallback_history_fact],
        tool_policy={"session_capable": True},
        metadata={
            "source": "gateway",
            "fallback_history_fact": fallback_history_fact,
        },
    )

    executor.execute(request)

    assert len(prompts) == 2
    assert prompts[1].count(fallback_history_fact) == 1


def test_codex_executor_successful_resume_does_not_inject_fallback_history(monkeypatch, tmp_path):
    monkeypatch.setenv("MENTE_SESSIONFUL_EXECUTION_ENABLED", "1")
    monkeypatch.setenv("MENTE_SESSIONFUL_EXECUTION_SOURCES", "gateway")
    payloads: list[tuple[str, KernelSessionRequest]] = []
    fallback_history_fact = 'Conversation history (JSON):\n[{"role":"user","content":"before"}]'

    class _Runner:
        def run(self, *, payload, session, runtime_config):
            payloads.append((payload.prompt, session))
            return KernelExecutionResult(
                status="success",
                assistant_summary="ok",
                debug={"thread_id": "thread-123"},
            )

    executor = CodexExecutor(codex_binary="codex", runner=_Runner())
    request = ExecutionRequest(
        task_id="task_1",
        session_id="session_1",
        task_type="conversation",
        objective="Reply",
        user_request="Reply to the user",
        workspace=str(tmp_path),
        execution_mode=ExecutionMode.SESSIONFUL,
        execution_session=ExecutionSession(
            mode=SessionMode.RESUME,
            continuity_id="thread-123",
        ),
        tool_policy={"session_capable": True},
        metadata={
            "source": "gateway",
            "fallback_history_fact": fallback_history_fact,
        },
    )

    result = executor.execute(request)

    assert result.status == "success"
    assert len(payloads) == 1
    assert payloads[0][1].mode is KernelSessionMode.SESSION
    assert fallback_history_fact not in payloads[0][0]


def test_codex_executor_fails_closed_for_disallowed_continuity_source(monkeypatch, tmp_path):
    monkeypatch.setenv("MENTE_SESSIONFUL_EXECUTION_ENABLED", "1")
    monkeypatch.setenv("MENTE_SESSIONFUL_EXECUTION_SOURCES", "api_server")
    captured: dict[str, object] = {}

    class _Runner:
        def run(self, *, payload, session, runtime_config):
            captured["session"] = session
            return KernelExecutionResult(status="success", assistant_summary="ok")

    executor = CodexExecutor(codex_binary="codex", runner=_Runner())
    request = ExecutionRequest(
        task_id="task_1",
        session_id="session_1",
        task_type="conversation",
        objective="Reply",
        user_request="Reply to the user",
        workspace=str(tmp_path),
        execution_mode=ExecutionMode.SESSIONFUL,
        execution_session=ExecutionSession(mode=SessionMode.START),
        tool_policy={"session_capable": True},
        metadata={"source": "gateway"},
    )

    result = executor.execute(request)

    assert captured["session"].mode is KernelSessionMode.STATELESS
    assert result.metadata["execution_session"] == {
        "mode": "stateless",
        "requested_mode": "start",
        "effective_mode": "stateless",
        "source": "gateway",
        "session_capable": True,
        "continuity_id": None,
        "continuity_status": "fallback_stateless",
        "fallback_reason": "source_not_allowed",
    }


def test_codex_executor_uses_content_runtime_profile_for_wechat_publish_tasks(
    monkeypatch, tmp_path
):
    monkeypatch.delenv("MENTE_SESSIONFUL_EXECUTION_ENABLED", raising=False)
    captured: dict[str, object] = {}

    class _Runner:
        def run(self, *, payload, session, runtime_config):
            captured["runtime_config"] = runtime_config
            return KernelExecutionResult(status="success", assistant_summary="ok")

    executor = CodexExecutor(codex_binary="codex", runner=_Runner())
    request = ExecutionRequest(
        task_id="task_1",
        session_id="session_1",
        task_type="conversation",
        objective="Draft and publish a WeChat article.",
        user_request="帮我写公众号文案并发布草稿",
        workspace=str(tmp_path),
        skill_refs=["media/wechat-publisher", "imagegen"],
        tool_policy={"session_capable": True},
        metadata={"source": "gateway", "task_profile": "content_publishing"},
    )

    result = executor.execute(request)

    assert result.status == "success"
    overrides = captured["runtime_config"].to_codex_overrides()
    assert f"base_instructions={json.dumps(MENTE_CONTENT_BASE_INSTRUCTIONS, ensure_ascii=True)}" in overrides
    assert (
        f"model_auto_compact_token_limit={MENTE_DEFAULT_AUTO_COMPACT_TOKEN_LIMIT}"
        in overrides
    )
    assert "agents.job_max_runtime_seconds=300" in overrides


def test_codex_executor_marks_missing_thread_id_when_session_start_returns_none(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("MENTE_SESSIONFUL_EXECUTION_ENABLED", "1")

    class _Runner:
        def run(self, *, payload, session, runtime_config):
            return KernelExecutionResult(status="success", assistant_summary="ok")

    executor = CodexExecutor(codex_binary="codex", runner=_Runner())
    request = ExecutionRequest(
        task_id="task_1",
        session_id="session_1",
        task_type="conversation",
        objective="Reply",
        user_request="Reply to the user",
        workspace=str(tmp_path),
        execution_mode=ExecutionMode.SESSIONFUL,
        execution_session=ExecutionSession(mode=SessionMode.START),
        tool_policy={
            "session_capable": True,
            "bridge_tools": ["mente_memory_query"],
        },
        metadata={"source": "api_server"},
    )

    result = executor.execute(request)

    assert result.metadata["execution_session"] == {
        "mode": "start",
        "requested_mode": "start",
        "effective_mode": "start",
        "source": "api_server",
        "session_capable": True,
        "continuity_id": None,
        "continuity_status": "missing_continuity_id",
        "fallback_reason": "missing_thread_id",
    }


def test_execution_request_can_carry_tool_policy_without_cli_details():
    policy = ToolExposurePolicy(
        policy_id="gateway:engineering",
        source="gateway",
        native_tools=["shell"],
        bridge_tools=["mente_memory_query"],
        session_capable=False,
    )
    request = ExecutionRequest(
        task_id="task_1",
        session_id="session_1",
        task_type="engineering",
        objective="Inspect repository",
        user_request="inspect repository",
        workspace=".",
        tool_policy=policy,
    )

    payload = request.model_dump(mode="json")

    assert payload["tool_policy"] == {
        "policy_id": "gateway:engineering",
        "source": "gateway",
        "native_tools": ["shell"],
        "bridge_tools": ["mente_memory_query"],
        "session_capable": False,
    }
    assert "command" not in payload
    assert "argv" not in payload
    assert "schema_path" not in payload


def test_codex_executor_builds_command():
    executor = CodexExecutor(codex_binary="codex")
    request = ExecutionRequest(
        task_id="task_1",
        session_id="session_1",
        task_type="engineering",
        objective="Inspect repository",
        user_request="inspect repository",
        workspace=".",
    )
    cmd = executor.build_command(request, output_schema="schema.json")
    assert cmd[0] == "codex"
    assert cmd[1] == "exec"
    assert "--ask-for-approval" not in cmd
    assert "--ephemeral" in cmd
    assert "--ignore-user-config" in cmd
    assert "--ignore-rules" in cmd
    assert "--full-auto" in cmd
    assert "--sandbox" in cmd
    assert 'sandbox_workspace_write.network_access=true' in cmd
    assert any("Inspect repository" in part for part in cmd)

    schema_arg = cmd[cmd.index("--output-schema") + 1]
    assert schema_arg.endswith(".json")


def test_codex_executor_builds_command_from_runtime_launch_config():
    runtime_config = RuntimeConfig(
        runtime_home=Path("/private/codex-home"),
        sandbox="danger-full-access",
        approval_policy="on-request",
        skip_git_repo_check=False,
        color="always",
    )
    executor = CodexExecutor(codex_binary="codex", runtime_config=runtime_config)
    request = ExecutionRequest(
        task_id="task_1",
        session_id="session_1",
        task_type="engineering",
        objective="Inspect repository",
        user_request="inspect repository",
        workspace="/workspace/repo",
    )

    cmd = executor.build_command(request, output_schema="schema.json")

    assert "--dangerously-bypass-approvals-and-sandbox" not in cmd
    assert "--sandbox" in cmd
    assert cmd[cmd.index("--sandbox") + 1] == "danger-full-access"
    assert "--full-auto" not in cmd
    assert "--skip-git-repo-check" not in cmd
    assert cmd[cmd.index("--color") + 1] == "always"


def test_vendored_launcher_matches_codex_executor_command_and_env():
    runtime_config = RuntimeConfig(
        runtime_home=Path("/private/codex-home"),
        codex_config={"model": "gpt-5.5"},
        subprocess_env={"MENTE_CODEX_API_KEY": "sk-private"},
    )
    executor = CodexExecutor(codex_binary="codex", runtime_config=runtime_config)
    request = ExecutionRequest(
        task_id="task_1",
        session_id="session_1",
        task_type="engineering",
        objective="Inspect repository",
        user_request="inspect repository",
        workspace="/workspace/repo",
    )
    payload = KernelExecutionPayload(
        prompt=executor.build_prompt(request),
        workspace=request.workspace,
        tool_policy=None,
    )

    vendored_command = build_stateless_command(
        codex_binary="codex",
        payload=payload,
        session=KernelSessionRequest(),
        sandbox="workspace-write",
        approval_policy="never",
        runtime_config=runtime_config,
        output_last_message="/tmp/out.txt",
        output_schema="/tmp/schema.json",
        workdir="/tmp/mente-codex-workdir-123",
        add_dirs=["/workspace/repo"],
    )
    executor_command = executor.build_command(
        request,
        output_last_message="/tmp/out.txt",
        output_schema="/tmp/schema.json",
        config_overrides=runtime_config.to_codex_overrides(),
        workdir="/tmp/mente-codex-workdir-123",
        add_dirs=["/workspace/repo"],
        runtime_config=runtime_config,
    )

    assert vendored_command == executor_command
    assert build_private_runtime_env(
        Path("/private/codex-home"),
        {"MENTE_CODEX_API_KEY": "sk-private"},
    ) == executor._build_subprocess_env(Path("/private/codex-home"))


def test_render_execution_prompt_and_fingerprint_are_stable():
    request = ExecutionRequest(
        task_id="task_1",
        session_id="session_1",
        task_type="conversation",
        objective="Reply",
        user_request="Reply",
        workspace=".",
        memory_facts=["Memory: User prefers concise replies."],
    )

    prompt = render_execution_prompt(request)
    fingerprint = build_prompt_fingerprint(prompt)
    second_request = request.model_copy()
    second_prompt = render_execution_prompt(second_request)

    assert "Task:" in prompt
    assert "Context:" in prompt
    assert "Return JSON matching the required schema." in prompt
    assert "Do not invent prior preferences" in prompt
    assert fingerprint == build_prompt_fingerprint(prompt)
    assert prompt == second_prompt
    assert fingerprint == build_prompt_fingerprint(second_prompt)
    assert len(fingerprint) == 64
    assert "Task Type:" not in prompt
    assert "Memory Facts:" not in prompt
    assert "Response Contract:" not in prompt
    assert prompt.index("Context:") < prompt.index("User Request:")


def test_render_execution_prompt_forbids_fabricated_preferences_without_memory():
    request = ExecutionRequest(
        task_id="task_1",
        session_id="session_1",
        task_type="conversation",
        objective="Reply",
        user_request="Reply",
        workspace=".",
    )

    prompt = render_execution_prompt(request)

    assert "Context:" not in prompt
    assert "If no memory facts are provided" not in prompt
    assert "Do not invent prior preferences" in prompt


def test_render_execution_prompt_advertises_on_demand_memory_query_when_available():
    request = ExecutionRequest(
        task_id="task_1",
        session_id="session_1",
        task_type="conversation",
        objective="Reply",
        user_request="Reply",
        workspace=".",
        tool_policy={"bridge_tools": ["mente_memory_query", "mente_memory_save"]},
    )

    prompt = render_execution_prompt(request)

    assert "mente_memory_query" in prompt
    assert "Use mente_memory_query only when prior user or project context is needed." in prompt


def test_render_execution_prompt_recommends_mente_superpowers_for_project_development():
    request = ExecutionRequest(
        task_id="task_1",
        session_id="session_1",
        task_type="engineering",
        objective="Implement project feature",
        user_request="请帮我在这个项目里新增登录功能并完成测试",
        workspace=".",
    )

    prompt = render_execution_prompt(request)

    assert "Mente Superpowers:" in prompt
    assert "brainstorming" in prompt
    assert "writing-plans" in prompt
    assert "test-driven-development" in prompt
    assert "verification-before-completion" in prompt


def test_render_execution_prompt_prioritizes_explicit_skill_refs():
    request = ExecutionRequest(
        task_id="task_1",
        session_id="session_1",
        task_type="conversation",
        objective="Draft and publish a WeChat article",
        user_request="帮我写一篇公众号文案并发布草稿",
        workspace=".",
        skill_refs=["media/wechat-publisher", "imagegen"],
    )

    prompt = render_execution_prompt(request)

    assert "Skill Policy:" in prompt
    assert "Use the provided skill refs first" in prompt
    assert "do not do broad workspace exploration before checking them" in prompt.lower()
    assert "concrete file, config key, or workflow entrypoint" in prompt
    assert "Read the referenced skill instructions before broad exploration" in prompt
    assert "If the skill workflow is blocked by a real gap or failure" in prompt
    assert "fix the concrete blocker" in prompt
    assert "If the skill documentation names concrete scripts or commands" in prompt
    assert "run the most direct workflow entrypoint first" in prompt
    assert "Before finalizing, self-check the referenced skill requirements" in prompt
    assert "Execution Modes:" in prompt
    assert "Deterministic task mode" in prompt
    assert "Rigorous engineering mode" in prompt
    assert "artifacts_out" in prompt
    assert "completion_status" in prompt


def test_render_execution_prompt_adds_direct_workflow_policy_for_content_publishing():
    request = ExecutionRequest(
        task_id="task_1",
        session_id="session_1",
        task_type="conversation",
        objective="Draft and publish a WeChat article",
        user_request="帮我写一篇公众号文案并发布草稿",
        workspace=".",
        skill_refs=["media/wechat-publisher", "imagegen"],
        tool_policy={"bridge_tools": ["mente_wechat_publish_draft"]},
        metadata={"source": "gateway", "task_profile": "content_publishing"},
    )

    prompt = render_execution_prompt(request)

    assert "Workflow Policy:" in prompt
    assert "Use the provided publishing skill and bridge tool path directly." in prompt
    assert "Do not read large numbers of repository files" in prompt
    assert "call mcp__mente__mente_wechat_publish_draft to publish" in prompt
    assert "mcp__mente__mente_wechat_publish_draft is the primary publish entrypoint" in prompt
    assert "server mente / tool mente_wechat_publish_draft" in prompt
    assert "Treat create-article.js or publish.js as optional reference helpers only" in prompt
    assert "stop exploring and execute the managed flow immediately" in prompt
    assert "make reasonable defaults and continue" in prompt


def test_render_execution_prompt_adds_direct_workflow_policy_for_config_admin():
    request = ExecutionRequest(
        task_id="task_1",
        session_id="session_1",
        task_type="conversation",
        objective="Update Mente config",
        user_request="把 terminal.cwd 改成 / 并重启 gateway",
        workspace=".",
        skill_refs=["software-development/mente-config-admin"],
        metadata={"source": "gateway", "task_profile": "config_admin"},
    )

    prompt = render_execution_prompt(request)

    assert "Workflow Policy:" in prompt
    assert "Resolve the active config, env, or auth path first" in prompt
    assert "mente config path" in prompt
    assert "concrete config file, key, or service action" in prompt
    assert "do not scan the repository or home directory" in prompt
    assert "redact secrets in user-facing confirmations" in prompt
    assert "Restart or reload the gateway only if the changed setting requires it" in prompt


def test_render_execution_prompt_adds_inventory_triage_for_self_improvement_engineering_worker():
    request = ExecutionRequest(
        task_id="task_1",
        session_id="session_1",
        task_type="conversation",
        objective="Improve Mente's future behavior",
        user_request="调用 Codex runtime 去编程修改技能和工作流，不要只记忆。",
        workspace=".",
        role="worker",
        worker_lane="engineering",
        worker_skill_refs=["social-media/xhs-daily-news"],
        metadata={
            "source": "gateway",
            "lane": "engineering",
            "task_profile": "self_improvement",
            "mente_inventory": {
                "routing_hint": {
                    "selected_category": "skills",
                    "category_priority": [
                        {
                            "category": "skills",
                            "available": True,
                            "recommended_reads": ["skills/social-media/xhs-daily-news/SKILL.md"],
                        },
                        {
                            "category": "config",
                            "available": True,
                            "recommended_reads": ["config.yaml", ".env"],
                        },
                    ],
                },
                "skills": {
                    "referenced_refs": ["social-media/xhs-daily-news"],
                },
                "config": {
                    "config_path": "/tmp/.mente/config.yaml",
                },
                "automation": {
                    "jobs_file": "/tmp/.mente/cron/jobs.json",
                },
                "artifacts": {
                    "deep_research_output_root": "/tmp/deep-research",
                    "recent_paths": ["/tmp/deep-research/report.docx"],
                },
            },
        },
        memory_facts=[
            "Mente inventory:\n- Referenced skills: social-media/xhs-daily-news\n- Config path: /tmp/.mente/config.yaml\n- Automation jobs: 1 total, 1 enabled via /tmp/.mente/cron/jobs.json\n- Deep-research output root: /tmp/deep-research\n- Recent artifacts: /tmp/deep-research/report.docx"
        ],
    )

    prompt = render_execution_prompt(request)

    assert "Mente Inventory Routing Hint:" in prompt
    assert "Selected category: skills" in prompt
    assert "Category order: skills, config" in prompt
    assert "Start with skills" in prompt
    assert "Start with config" in prompt
    assert "Use the selected category" in prompt


def test_render_execution_prompt_marks_probe_only_skill_audit_turn_as_incomplete():
    request = ExecutionRequest(
        task_id="task_1",
        session_id="session_1",
        task_type="conversation",
        objective="Audit a Daily News skill",
        user_request="你帮我看看 daily news 技能，看看有哪些方面需要改进",
        workspace=".",
        role="worker",
        worker_lane="engineering",
        worker_skill_refs=["social-media/xhs-daily-news"],
        skill_refs=["social-media/xhs-daily-news"],
        metadata={"source": "gateway", "task_profile": "skill_audit", "lane": "engineering"},
    )

    prompt = render_execution_prompt(request)

    assert "Workflow Policy:" in prompt
    assert "Reading only SKILL.md, locating scripts, or announcing a next step is not a completed audit." in prompt
    assert "If you have not yet delivered concrete optimization findings with file references" in prompt
    assert "set `completion_status` to `blocked`" in prompt


def test_normalize_user_facing_summary_unwraps_user_facing_json_report():
    raw_summary = json.dumps(
        {
            "结论": "这个 skill 能跑通基础链路，但实现质量和产出稳定性还有明显改进空间。",
            "findings": [
                {
                    "title": "发布文案没有使用转换后的正文",
                    "file": "/tmp/publish_to_xhs.py:122",
                    "detail": "最终发出去的正文仍然是固定模板，前面的改写结果没有被复用。",
                },
                {
                    "title": "标题生成使用 Python 内置 hash()，跨进程不稳定",
                    "file": "/tmp/generate_daily_news.py:152",
                    "detail": "相同输入在不同进程下可能产生不同标题前缀，影响复现。",
                },
            ],
            "优先级建议": [
                "先修发布文案复用问题。",
                "再修真实 fallback 和确定性标题逻辑。",
            ],
        },
        ensure_ascii=False,
    )

    normalized = normalize_user_facing_summary(raw_summary)

    assert normalized.startswith("这个 skill 能跑通基础链路")
    assert '{"结论"' not in normalized
    assert "主要问题：" in normalized
    assert "1. 发布文案没有使用转换后的正文 [/tmp/publish_to_xhs.py:122]" in normalized
    assert "优先级建议：" in normalized
    assert "- 先修发布文案复用问题。" in normalized


def test_render_execution_prompt_adds_report_delivery_policy_for_deep_research():
    request = ExecutionRequest(
        task_id="task_1",
        session_id="session_1",
        task_type="conversation",
        objective="Complete a deep research report",
        user_request="深度研究一下采用菜籽油制备十三碳二酸的可行性，并输出完整报告",
        workspace=".",
        skill_refs=["research/deep-research-pro"],
        metadata={"source": "gateway", "task_profile": "deep_research"},
    )

    prompt = render_execution_prompt(request)

    assert "\nDeep Research Mode:" in prompt
    assert "\nResearch Mode:" not in prompt
    assert "Run the managed deep-research workflow directly instead of stopping at intermediate analysis." in prompt
    assert "Prefer the referenced skill entrypoint or direct parallel helper before manual reconstruction." in prompt
    assert "The canonical skill instructions file is SKILL.md; do not probe for README.md in the skill root." in prompt
    assert "When context already provides a direct launch command or entrypoint, execute it before extra directory probing." in prompt
    assert "Workflow Policy:" in prompt
    assert "Use the provided deep-research skill directly and complete the full report workflow in this turn." in prompt
    assert "Use delegate_task to launch parallel chapter workers" in prompt
    assert "chapter_1 + chapter_4" in prompt
    assert "chapter_2 + chapter_3" in prompt
    assert "chapter_5 + chapter_6 + chapter_7" in prompt
    assert "Do not stop at intermediate findings or end by asking whether the user wants the formal report." in prompt
    assert "Generate the final report artifacts in Markdown, HTML, and DOCX, then report the exact paths in the final reply." in prompt
    assert "If one format generation step fails" in prompt
    assert "The task is complete only after the report artifacts exist" in prompt


def test_render_execution_prompt_adds_direct_delivery_policy_for_artifact_followup():
    request = ExecutionRequest(
        task_id="task_1",
        session_id="session_1",
        task_type="conversation",
        objective="Deliver existing report artifacts",
        user_request="把刚才生成的三个报告上传到飞书云文档里",
        workspace=".",
        artifacts_in=["report.md", "report.html", "report.docx"],
        metadata={"source": "gateway", "task_profile": "artifact_delivery"},
    )

    prompt = render_execution_prompt(request)

    assert "Workflow Policy:" in prompt
    assert "narrow follow-up artifact delivery request" in prompt
    assert "Use the provided artifact paths directly" in prompt
    assert "Do not scan large parts of the repository" in prompt
    assert "upload or share the listed files immediately" in prompt
    assert "The task is complete only after the requested artifact delivery is done" in prompt


def test_render_execution_prompt_uses_lightweight_skill_fallback_when_no_explicit_refs():
    request = ExecutionRequest(
        task_id="task_1",
        session_id="session_1",
        task_type="conversation",
        objective="Reply",
        user_request="帮我处理一个任务",
        workspace=".",
    )

    prompt = render_execution_prompt(request)

    assert "Skill Policy:" in prompt
    assert "If no skill refs are provided" in prompt
    assert "at most one narrow skill check" in prompt
    assert "Do not scan the full skills tree" in prompt


def test_render_execution_prompt_does_not_recommend_mente_superpowers_for_plain_chat():
    request = ExecutionRequest(
        task_id="task_1",
        session_id="session_1",
        task_type="conversation",
        objective="Reply",
        user_request="你好",
        workspace=".",
    )

    prompt = render_execution_prompt(request)

    assert "Mente Superpowers:" not in prompt


def test_render_execution_prompt_uses_thin_prompt_for_plain_chat():
    request = ExecutionRequest(
        task_id="task_1",
        session_id="session_1",
        task_type="conversation",
        objective="Reply",
        user_request="你是什么大模型",
        workspace=".",
        memory_facts=["Session context:\n请用中文简洁回答。"],
    )

    prompt = render_execution_prompt(request)

    assert "Task:" in prompt
    assert "Context:" in prompt
    assert "Session context:" in prompt
    assert "Reply directly to the user's latest message." in prompt
    assert "Answer directly in the user's language and keep it concise." in prompt
    assert "Do not claim prior context, actions, or preferences that are not provided." in prompt
    assert "Skill Policy:" not in prompt
    assert "Execution Modes:" not in prompt
    assert "Memory Access:" not in prompt
    assert "Mente Superpowers:" not in prompt
    assert "If no skill refs are provided" not in prompt
    assert len(prompt) < 700


def test_render_execution_prompt_uses_thin_prompt_for_director_lane():
    request = ExecutionRequest(
        task_id="task_1",
        session_id="session_1",
        task_type="conversation",
        objective="Reply",
        user_request="继续",
        workspace=".",
        memory_facts=["Session context:\n请延续中文对话。"],
        metadata={"lane": "director"},
    )

    prompt = render_execution_prompt(request)

    assert "Conversation Mode:" in prompt
    assert "Reply directly to the user's latest message." in prompt
    assert "Execution Modes:" not in prompt
    assert "Research Mode:" not in prompt
    assert "Writing Mode:" not in prompt


def test_render_execution_prompt_uses_research_prompt_for_research_lane():
    request = ExecutionRequest(
        task_id="task_1",
        session_id="session_1",
        task_type="conversation",
        objective="Research the market positioning of open-source coding agents",
        user_request="调研一下开源 coding agent 的市场定位和差异",
        workspace=".",
        metadata={"lane": "research"},
    )

    prompt = render_execution_prompt(request)

    assert "Task:" in prompt
    assert "Research Mode:" in prompt
    assert "Gather only the evidence needed to answer the request well." in prompt
    assert "Deliver the analysis directly instead of turning it into an engineering workflow." in prompt
    assert "Rigorous engineering mode" not in prompt
    assert "Writing Mode:" not in prompt


def test_render_execution_prompt_uses_writing_prompt_for_writing_lane():
    request = ExecutionRequest(
        task_id="task_1",
        session_id="session_1",
        task_type="conversation",
        objective="Draft a concise launch announcement",
        user_request="帮我写一版产品发布短文案，语气克制一点",
        workspace=".",
        metadata={"lane": "writing"},
    )

    prompt = render_execution_prompt(request)

    assert "Task:" in prompt
    assert "Writing Mode:" in prompt
    assert "Produce the requested draft or rewrite directly." in prompt
    assert "Prefer delivering the requested wording over engineering-style process narration." in prompt
    assert "Rigorous engineering mode" not in prompt
    assert "Research Mode:" not in prompt


def test_render_execution_prompt_keeps_full_prompt_for_engineering_requests():
    request = ExecutionRequest(
        task_id="task_1",
        session_id="session_1",
        task_type="conversation",
        objective="Implement a feature in this repository",
        user_request="请帮我在这个项目里新增登录功能并完成测试",
        workspace=".",
    )

    prompt = render_execution_prompt(request)

    assert "Skill Policy:" in prompt
    assert "Execution Modes:" in prompt
    assert "Deterministic task mode" in prompt
    assert "Rigorous engineering mode" in prompt


def test_render_execution_prompt_directs_memory_writes_to_canonical_mente_home():
    request = ExecutionRequest(
        task_id="task_1",
        session_id="session_1",
        task_type="engineering",
        objective="Inspect repository",
        user_request="Read and update the user's memory files if needed.",
        workspace=".",
    )

    prompt = render_execution_prompt(request)

    assert "Memory Access:" in prompt
    assert "Use MENTE_HOME for any Mente-managed memory files or directories." in prompt
    assert "Do not hardcode ~/.mente or $HOME/.mente when reading or writing memory files." in prompt
    assert "The canonical file-backed memory directory is <MENTE_HOME>/memories." in prompt


def test_codex_executor_uses_dangerous_bypass_for_full_access():
    executor = CodexExecutor(
        codex_binary="codex",
        sandbox="danger-full-access",
        approval_policy="never",
    )
    request = ExecutionRequest(
        task_id="task_1",
        session_id="session_1",
        task_type="engineering",
        objective="Inspect repository",
        user_request="inspect repository",
        workspace=".",
    )

    cmd = executor.build_command(request, output_schema="schema.json")

    assert "--dangerously-bypass-approvals-and-sandbox" in cmd
    assert "--full-auto" not in cmd
    assert "--sandbox" not in cmd


def test_codex_executor_execute_uses_private_codex_home(monkeypatch, tmp_path):
    mente_home = tmp_path / ".mente"
    monkeypatch.setenv("MENTE_HOME", str(mente_home))
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "public-codex-home"))
    captured: dict[str, object] = {}

    class _Runner:
        def run(self, *, payload, session, runtime_config):
            captured["payload"] = payload
            captured["session"] = session
            captured["runtime_config"] = runtime_config
            captured["runtime_home_exists"] = runtime_config.runtime_home.is_dir()
            return KernelExecutionResult(
                status="success",
                assistant_summary="ok",
            )

    executor = CodexExecutor(codex_binary="codex", runner=_Runner())
    request = ExecutionRequest(
        task_id="task_1",
        session_id="session_1",
        task_type="conversation",
        objective="Reply",
        user_request="Reply to the user",
        workspace=str(tmp_path),
    )

    result = executor.execute(request)

    assert result.status == "success"
    assert result.summary == "ok"
    runtime_config = captured["runtime_config"]
    assert isinstance(runtime_config, RuntimeConfig)
    assert runtime_config.runtime_home == _agent_runtime_home(mente_home, "product_engineering")
    assert captured["runtime_home_exists"] is True


def test_codex_executor_skips_public_auth_seed_when_private_api_key_is_present(monkeypatch, tmp_path):
    public_codex_home = tmp_path / "public-codex-home"
    public_codex_home.mkdir()
    (public_codex_home / "auth.json").write_text('{"OPENAI_API_KEY":"sk-stale"}', encoding="utf-8")
    monkeypatch.setenv("CODEX_HOME", str(public_codex_home))

    executor = CodexExecutor()
    runtime_config = RuntimeConfig(
        runtime_home=tmp_path / "private-codex-home",
        subprocess_env={"MENTE_CODEX_API_KEY": "sk-private"},
    )
    executor._seed_auth_into_isolated_home(runtime_config.runtime_home, runtime_config)

    assert not (runtime_config.runtime_home / "auth.json").exists()


def test_codex_executor_prefetches_memory_into_request(monkeypatch, tmp_path):
    memory_repo = InMemoryMemoryRepository()
    memory_repo.save(
        MemoryRecord(
            memory_id="mem_1",
            session_id="session_1",
            task_id="task_old",
            task_type="conversation",
            source="gateway",
            scope="session",
            fact="User prefers concise replies.",
        )
    )
    captured: dict[str, object] = {}

    class _Runner:
        def run(self, *, payload, session, runtime_config):
            captured["payload"] = payload
            return KernelExecutionResult(status="success", assistant_summary="ok")

    monkeypatch.setenv("MENTE_HOME", str(tmp_path / ".mente"))
    executor = CodexExecutor(codex_binary="codex", runner=_Runner(), memory_repository=memory_repo)
    request = ExecutionRequest(
        task_id="task_1",
        session_id="session_1",
        task_type="conversation",
        objective="Reply",
        user_request="Reply to the user",
        workspace=str(tmp_path),
        metadata={"source": "gateway"},
    )

    result = executor.execute(request)

    assert result.status == "success"
    assert "Memory: User prefers concise replies." in captured["payload"].prompt


def test_codex_executor_keeps_memory_injection_mente_owned_in_sessionful_mode(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("MENTE_SESSIONFUL_EXECUTION_ENABLED", "1")
    memory_repo = InMemoryMemoryRepository()
    memory_repo.save(
        MemoryRecord(
            memory_id="mem_1",
            session_id="session_1",
            task_id="task_old",
            task_type="conversation",
            source="api_server",
            scope="session",
            fact="User prefers concise replies.",
        )
    )
    captured: dict[str, object] = {}

    class _Runner:
        def run(self, *, payload, session, runtime_config):
            captured["payload"] = payload
            captured["session"] = session
            return KernelExecutionResult(status="success", assistant_summary="ok")

    executor = CodexExecutor(codex_binary="codex", runner=_Runner(), memory_repository=memory_repo)
    request = ExecutionRequest(
        task_id="task_1",
        session_id="session_1",
        task_type="conversation",
        objective="Reply",
        user_request="Reply to the user",
        workspace=str(tmp_path),
        execution_mode=ExecutionMode.SESSIONFUL,
        execution_session=ExecutionSession(mode=SessionMode.START),
        tool_policy={
            "session_capable": True,
            "bridge_tools": ["mente_memory_query"],
        },
        metadata={"source": "api_server"},
    )

    result = executor.execute(request)

    assert result.status == "success"
    assert "Memory: User prefers concise replies." not in captured["payload"].prompt
    assert "mente_memory_query" in captured["payload"].prompt
    assert captured["session"].mode is KernelSessionMode.SESSION


def test_codex_executor_keeps_worker_and_session_summaries_in_thin_prompt_for_worker_runs(
    tmp_path,
):
    memory_repo = InMemoryMemoryRepository()
    memory_repo.save(
        MemoryRecord(
            memory_id="mem_worker_summary",
            session_id="session_1",
            task_id="task_old_worker_summary",
            task_type="conversation",
            source="gateway",
            scope="session",
            kind="worker_lane_summary:research",
            fact="Worker lane summary (research): current shortlist and open diligence gaps.",
            score=1.0,
        )
    )
    memory_repo.save(
        MemoryRecord(
            memory_id="mem_session_summary",
            session_id="session_1",
            task_id="task_old_session_summary",
            task_type="conversation",
            source="gateway",
            scope="session",
            kind="session_summary",
            fact="Session summary: user wants the answer as a concise sourcing memo.",
            score=2.0,
        )
    )
    memory_repo.save(
        MemoryRecord(
            memory_id="mem_generic_session",
            session_id="session_1",
            task_id="task_old_generic_session",
            task_type="conversation",
            source="gateway",
            scope="session",
            fact="Ordinary session fact that should remain runtime-query only.",
            score=5.0,
        )
    )
    captured: dict[str, object] = {}

    class _Runner:
        def run(self, *, payload, session, runtime_config):
            captured["payload"] = payload
            return KernelExecutionResult(status="success", assistant_summary="ok")

    executor = CodexExecutor(codex_binary="codex", runner=_Runner(), memory_repository=memory_repo)
    request = ExecutionRequest(
        task_id="task_worker_1",
        session_id="session_1",
        task_type="conversation",
        objective="Continue delegated research",
        user_request="Continue delegated research",
        workspace=str(tmp_path),
        role="worker",
        worker_lane="research",
        memory_facts=["Task brief: update the supplier memo."],
        tool_policy={
            "bridge_tools": ["mente_memory_query", "mente_memory_save"],
        },
        metadata={
            "source": "gateway",
            "workflow_contract": {
                "workflow_id": "gateway_conversation",
                "memory_read": {
                    "mode": "runtime_on_demand_query",
                    "enabled": True,
                    "session_summary": {
                        "enabled": True,
                        "scope": "session",
                        "kind": "session_summary",
                        "priority": "before_generic_memories",
                        "max_results": 1,
                        "counts_toward_existing_budgets": True,
                    },
                },
            },
        },
    )

    result = executor.execute(request)
    prompt = captured["payload"].prompt

    assert result.status == "success"
    assert "Worker lane summary (research): current shortlist and open diligence gaps." in prompt
    assert "Session summary: user wants the answer as a concise sourcing memo." in prompt
    assert "Ordinary session fact that should remain runtime-query only." not in prompt
    assert "Task brief: update the supplier memo." in prompt
    assert "mente_memory_query" in prompt


def test_codex_executor_injects_mente_inventory_for_direct_self_improvement_worker_request(
    monkeypatch,
    tmp_path,
):
    mente_home = tmp_path / ".mente"
    skill_root = mente_home / "skills" / "social-media" / "xhs-daily-news"
    cron_dir = mente_home / "cron"
    deep_research_root = tmp_path / "deep-research"
    skill_root.mkdir(parents=True, exist_ok=True)
    cron_dir.mkdir(parents=True, exist_ok=True)
    deep_research_root.mkdir(parents=True, exist_ok=True)
    (skill_root / "SKILL.md").write_text(
        "---\nname: xhs-daily-news\ndescription: Daily news skill.\n---\n",
        encoding="utf-8",
    )
    (mente_home / "config.yaml").write_text(
        f"mente:\n  deep_research:\n    output_root: {deep_research_root}\n",
        encoding="utf-8",
    )
    (cron_dir / "jobs.json").write_text(
        '{"jobs":[{"id":"job-1","name":"Daily News","enabled":true,"schedule":"0 9 * * *"}]}\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("MENTE_HOME", str(mente_home))
    monkeypatch.setenv("HERMES_HOME", str(mente_home))
    captured: dict[str, object] = {}

    class _Runner:
        def run(self, *, payload, session, runtime_config):
            captured["prompt"] = payload.prompt
            return KernelExecutionResult(status="success", assistant_summary="ok")

    executor = CodexExecutor(codex_binary="codex", runner=_Runner())
    request = ExecutionRequest(
        task_id="task_worker_inventory",
        session_id="session_1",
        task_type="conversation",
        objective="Improve Mente's future behavior",
        user_request="调用 Codex runtime 去编程修改技能和工作流，不要只记忆。",
        workspace=str(tmp_path),
        role="worker",
        worker_lane="engineering",
        worker_skill_refs=["social-media/xhs-daily-news"],
        metadata={
            "source": "gateway",
            "lane": "engineering",
            "task_profile": "self_improvement",
        },
    )

    result = executor.execute(request)
    prompt = str(captured["prompt"])

    assert result.status == "success"
    assert "Mente inventory:" in prompt
    assert "social-media/xhs-daily-news" in prompt
    assert "jobs.json" in prompt


def test_codex_executor_uses_canonical_mente_skills_without_private_runtime_mirror(
    monkeypatch,
    tmp_path,
):
    mente_home = tmp_path / ".mente"
    skills_root = mente_home / "skills" / "media" / "wechat-publisher"
    skills_root.mkdir(parents=True, exist_ok=True)
    (skills_root / "SKILL.md").write_text(
        "---\nname: wechat-publisher\ndescription: Publish to WeChat drafts.\n---\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("MENTE_HOME", str(mente_home))
    captured: dict[str, object] = {}

    class _Runner:
        def run(self, *, payload, session, runtime_config):
            private_skills = runtime_config.runtime_home / ".agents" / "skills"
            canonical_skill = skills_root / "SKILL.md"
            captured["private_skills_exists"] = (
                private_skills.exists() or private_skills.is_symlink()
            )
            captured["canonical_skill_exists"] = canonical_skill.exists()
            captured["canonical_skill_contents"] = canonical_skill.read_text(encoding="utf-8")
            return KernelExecutionResult(status="success", assistant_summary="ok")

    executor = CodexExecutor(codex_binary="codex", runner=_Runner())
    request = ExecutionRequest(
        task_id="task_1",
        session_id="session_1",
        task_type="conversation",
        objective="Reply",
        user_request="Reply to the user",
        workspace=str(tmp_path),
    )

    result = executor.execute(request)

    assert result.status == "success"
    assert captured["private_skills_exists"] is False
    assert captured["canonical_skill_exists"] is True
    assert "wechat-publisher" in captured["canonical_skill_contents"]


def test_codex_executor_removes_private_skill_mirrors_without_symlinking(
    monkeypatch,
    tmp_path,
):
    mente_home = tmp_path / ".mente"
    canonical_skills = mente_home / "skills"
    skill_root = canonical_skills / "media" / "wechat-publisher"
    skill_root.mkdir(parents=True, exist_ok=True)
    (skill_root / "SKILL.md").write_text(
        "---\nname: wechat-publisher\ndescription: Publish to WeChat drafts.\n---\n",
        encoding="utf-8",
    )
    runtime_home = mente_home / "codex"
    stale_agents_skills = runtime_home / ".agents" / "skills"
    stale_agents_skills.mkdir(parents=True, exist_ok=True)
    (stale_agents_skills / "stale.txt").write_text("old copy", encoding="utf-8")
    monkeypatch.setenv("MENTE_HOME", str(mente_home))
    captured: dict[str, object] = {}

    class _Runner:
        def run(self, *, payload, session, runtime_config):
            target = runtime_config.runtime_home / ".agents" / "skills"
            captured["target_exists"] = target.exists() or target.is_symlink()
            captured["target_is_symlink"] = target.is_symlink()
            captured["canonical_skill_exists"] = (
                canonical_skills / "media" / "wechat-publisher" / "SKILL.md"
            ).exists()
            return KernelExecutionResult(status="success", assistant_summary="ok")

    executor = CodexExecutor(codex_binary="codex", runner=_Runner())
    request = ExecutionRequest(
        task_id="task_1",
        session_id="session_1",
        task_type="conversation",
        objective="Reply",
        user_request="Reply to the user",
        workspace=str(tmp_path),
    )

    result = executor.execute(request)

    assert result.status == "success"
    assert captured["target_exists"] is False
    assert captured["target_is_symlink"] is False
    assert captured["canonical_skill_exists"] is True


def test_codex_executor_does_not_copy_bundled_skills_into_private_runtime(monkeypatch, tmp_path):
    mente_home = tmp_path / ".mente"
    mente_home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("MENTE_HOME", str(mente_home))
    captured: dict[str, object] = {}

    class _Runner:
        def run(self, *, payload, session, runtime_config):
            private_skills = runtime_config.runtime_home / ".agents" / "skills"
            captured["private_skills_exists"] = (
                private_skills.exists() or private_skills.is_symlink()
            )
            return KernelExecutionResult(status="success", assistant_summary="ok")

    executor = CodexExecutor(codex_binary="codex", runner=_Runner())
    request = ExecutionRequest(
        task_id="task_1",
        session_id="session_1",
        task_type="engineering",
        objective="Build feature",
        user_request="Implement a feature in this project",
        workspace=str(tmp_path),
    )

    result = executor.execute(request)

    assert result.status == "success"
    assert captured["private_skills_exists"] is False


def test_codex_executor_links_private_runtime_memories_to_canonical_mente_memory(
    monkeypatch, tmp_path
):
    mente_home = tmp_path / ".mente"
    canonical_memories = mente_home / "memories"
    monkeypatch.setenv("MENTE_HOME", str(mente_home))
    runtime_config = RuntimeConfig(runtime_home=tmp_path / "private-codex-home")
    captured: dict[str, object] = {}

    class _Runner:
        def run(self, *, payload, session, runtime_config):
            runtime_memories = runtime_config.runtime_home / "memories"
            captured["runtime_memories_is_symlink"] = runtime_memories.is_symlink()
            captured["runtime_memories_target"] = runtime_memories.resolve()
            (runtime_memories / "USER.md").write_text("User prefers unified memory.", encoding="utf-8")
            return KernelExecutionResult(status="success", assistant_summary="ok")

    executor = CodexExecutor(codex_binary="codex", runner=_Runner(), runtime_config=runtime_config)
    request = ExecutionRequest(
        task_id="task_1",
        session_id="session_1",
        task_type="conversation",
        objective="Reply",
        user_request="Reply to the user",
        workspace=str(tmp_path),
    )

    result = executor.execute(request)

    assert result.status == "success"
    assert captured["runtime_memories_is_symlink"] is True
    assert captured["runtime_memories_target"] == canonical_memories.resolve()
    assert (canonical_memories / "USER.md").read_text(encoding="utf-8") == "User prefers unified memory."


def test_codex_executor_preserves_existing_private_runtime_memories_before_linking(
    monkeypatch, tmp_path
):
    mente_home = tmp_path / ".mente"
    runtime_home = tmp_path / "private-codex-home"
    legacy_memories = runtime_home / "memories"
    legacy_memories.mkdir(parents=True)
    (legacy_memories / "user-preferences.md").write_text("legacy private note", encoding="utf-8")
    monkeypatch.setenv("MENTE_HOME", str(mente_home))
    runtime_config = RuntimeConfig(runtime_home=runtime_home)

    class _Runner:
        def run(self, *, payload, session, runtime_config):
            assert (runtime_config.runtime_home / "memories").is_symlink()
            return KernelExecutionResult(status="success", assistant_summary="ok")

    executor = CodexExecutor(codex_binary="codex", runner=_Runner(), runtime_config=runtime_config)
    request = ExecutionRequest(
        task_id="task_1",
        session_id="session_1",
        task_type="conversation",
        objective="Reply",
        user_request="Reply to the user",
        workspace=str(tmp_path),
    )

    result = executor.execute(request)

    assert result.status == "success"
    backups = list(runtime_home.glob("memories.legacy-*"))
    assert len(backups) == 1
    assert (backups[0] / "user-preferences.md").read_text(encoding="utf-8") == "legacy private note"
    assert (runtime_home / "memories").resolve() == (mente_home / "memories").resolve()


def test_codex_executor_links_private_runtime_dot_mente_memory_aliases_to_canonical_mente_memory(
    monkeypatch, tmp_path
):
    mente_home = tmp_path / ".mente"
    canonical_memories = mente_home / "memories"
    runtime_config = RuntimeConfig(runtime_home=tmp_path / "private-codex-home")
    monkeypatch.setenv("MENTE_HOME", str(mente_home))
    captured: dict[str, object] = {}

    class _Runner:
        def run(self, *, payload, session, runtime_config):
            dot_mente_dir = runtime_config.runtime_home / ".mente"
            alias_memories = dot_mente_dir / "memories"
            alias_memory = dot_mente_dir / "memory"
            captured["dot_mente_exists"] = dot_mente_dir.is_dir()
            captured["alias_memories_is_symlink"] = alias_memories.is_symlink()
            captured["alias_memories_target"] = alias_memories.resolve()
            captured["alias_memory_is_symlink"] = alias_memory.is_symlink()
            captured["alias_memory_target"] = alias_memory.resolve()
            (alias_memories / "PROFILE.md").write_text("Unified profile memory.", encoding="utf-8")
            (alias_memory / "TASK.md").write_text("Unified task memory.", encoding="utf-8")
            return KernelExecutionResult(status="success", assistant_summary="ok")

    executor = CodexExecutor(codex_binary="codex", runner=_Runner(), runtime_config=runtime_config)
    request = ExecutionRequest(
        task_id="task_1",
        session_id="session_1",
        task_type="conversation",
        objective="Reply",
        user_request="Reply to the user",
        workspace=str(tmp_path),
    )

    result = executor.execute(request)

    assert result.status == "success"
    assert captured["dot_mente_exists"] is True
    assert captured["alias_memories_is_symlink"] is True
    assert captured["alias_memories_target"] == canonical_memories.resolve()
    assert captured["alias_memory_is_symlink"] is True
    assert captured["alias_memory_target"] == canonical_memories.resolve()
    assert (canonical_memories / "PROFILE.md").read_text(encoding="utf-8") == "Unified profile memory."
    assert (canonical_memories / "TASK.md").read_text(encoding="utf-8") == "Unified task memory."


def test_codex_executor_execute_seeds_auth_without_copying_shared_state(monkeypatch, tmp_path):
    from hermes_cli.auth import resolve_codex_runtime_credentials as _real_resolve_codex_runtime_credentials

    monkeypatch.setattr(
        "mente.executors.runtime_auth.resolve_codex_runtime_credentials",
        _real_resolve_codex_runtime_credentials,
    )
    mente_home = tmp_path / ".mente"
    public_codex_home = tmp_path / "public-codex-home"
    public_codex_home.mkdir()
    (public_codex_home / "auth.json").write_text(
        json.dumps({"OPENAI_API_KEY": "test-openai-key"}),
        encoding="utf-8",
    )
    (public_codex_home / "config.toml").write_text('model = "gpt-5"', encoding="utf-8")
    (public_codex_home / "rules").mkdir()
    (public_codex_home / "rules" / "default.rules").write_text("never share", encoding="utf-8")
    mente_home.mkdir(parents=True, exist_ok=True)
    (mente_home / "auth.json").write_text(
        json.dumps({
            "version": 1,
            "providers": {
                "openai-codex": {
                    "tokens": {
                        "access_token": "private-access-token",
                        "refresh_token": "private-refresh-token",
                    },
                    "last_refresh": "2026-05-05T00:00:00Z",
                    "auth_mode": "chatgpt",
                }
            },
        }),
        encoding="utf-8",
    )
    monkeypatch.setenv("MENTE_HOME", str(mente_home))
    monkeypatch.setenv("HERMES_HOME", str(mente_home))
    monkeypatch.setenv("CODEX_HOME", str(public_codex_home))
    captured: dict[str, object] = {}

    class _Runner:
        def run(self, *, payload, session, runtime_config):
            isolated_home = runtime_config.runtime_home
            captured["auth_payload"] = json.loads((isolated_home / "auth.json").read_text(encoding="utf-8"))
            captured["config_exists"] = (isolated_home / "config.toml").exists()
            captured["rules_exist"] = (isolated_home / "rules" / "default.rules").exists()
            return KernelExecutionResult(status="success", assistant_summary="ok")

    executor = CodexExecutor(codex_binary="codex", runner=_Runner())
    request = ExecutionRequest(
        task_id="task_1",
        session_id="session_1",
        task_type="conversation",
        objective="Reply",
        user_request="Reply to the user",
        workspace=str(tmp_path),
    )

    result = executor.execute(request)

    assert result.status == "success"
    assert captured["auth_payload"] == {"OPENAI_API_KEY": "private-access-token"}
    assert captured["config_exists"] is False
    assert captured["rules_exist"] is False


def test_codex_executor_seeds_runtime_auth_from_hermes_store_not_public_codex_home(
    monkeypatch, tmp_path
):
    from hermes_cli.auth import resolve_codex_runtime_credentials as _real_resolve_codex_runtime_credentials

    monkeypatch.setattr(
        "mente.executors.runtime_auth.resolve_codex_runtime_credentials",
        _real_resolve_codex_runtime_credentials,
    )
    hermes_home = tmp_path / ".mente"
    public_codex_home = tmp_path / "public-codex-home"
    hermes_home.mkdir(parents=True, exist_ok=True)
    public_codex_home.mkdir(parents=True, exist_ok=True)
    (public_codex_home / "auth.json").write_text(
        json.dumps({"OPENAI_API_KEY": "public-stale-key"}),
        encoding="utf-8",
    )
    (hermes_home / "auth.json").write_text(
        json.dumps({
            "version": 1,
            "providers": {
                "openai-codex": {
                    "tokens": {
                        "access_token": "private-access-token",
                        "refresh_token": "private-refresh-token",
                    },
                    "last_refresh": "2026-05-05T00:00:00Z",
                    "auth_mode": "chatgpt",
                }
            },
        }),
        encoding="utf-8",
    )
    monkeypatch.setenv("MENTE_HOME", str(hermes_home))
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    monkeypatch.setenv("CODEX_HOME", str(public_codex_home))
    captured: dict[str, object] = {}

    class _Runner:
        def run(self, *, payload, session, runtime_config):
            isolated_home = runtime_config.runtime_home
            captured["auth_payload"] = json.loads((isolated_home / "auth.json").read_text(encoding="utf-8"))
            return KernelExecutionResult(status="success", assistant_summary="ok")

    executor = CodexExecutor(codex_binary="codex", runner=_Runner())
    request = ExecutionRequest(
        task_id="task_1",
        session_id="session_1",
        task_type="conversation",
        objective="Reply",
        user_request="Reply to the user",
        workspace=str(tmp_path),
    )

    result = executor.execute(request)

    assert result.status == "success"
    assert captured["auth_payload"] == {"OPENAI_API_KEY": "private-access-token"}


def test_codex_executor_public_codex_home_only_fails_closed_when_private_runtime_auth_missing(
    monkeypatch, tmp_path
):
    from hermes_cli.auth import resolve_codex_runtime_credentials as _real_resolve_codex_runtime_credentials

    monkeypatch.setattr(
        "mente.executors.runtime_auth.resolve_codex_runtime_credentials",
        _real_resolve_codex_runtime_credentials,
    )
    public_codex_home = tmp_path / "public-codex-home"
    public_codex_home.mkdir(parents=True, exist_ok=True)
    (public_codex_home / "auth.json").write_text(
        json.dumps({"OPENAI_API_KEY": "public-only"}),
        encoding="utf-8",
    )
    monkeypatch.setenv("MENTE_HOME", str(tmp_path / ".mente"))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / ".mente"))
    monkeypatch.setenv("CODEX_HOME", str(public_codex_home))

    executor = CodexExecutor(codex_binary="codex")
    request = ExecutionRequest(
        task_id="task_1",
        session_id="session_1",
        task_type="conversation",
        objective="Reply",
        user_request="Reply to the user",
        workspace=str(tmp_path),
    )

    with pytest.raises(AuthError, match="No Codex credentials stored"):
        executor.execute(request)


def test_codex_executor_execute_passes_minimal_provider_overrides_without_copying_config(
    monkeypatch, tmp_path
):
    mente_home = tmp_path / ".mente"
    workspace = tmp_path / "workspace"
    profile_config = mente_home / "config.yaml"
    workspace_config = workspace / ".mente" / "config.yaml"
    profile_config.parent.mkdir(parents=True, exist_ok=True)
    workspace_config.parent.mkdir(parents=True, exist_ok=True)
    profile_config.write_text(
        "\n".join(
            [
                "codex:",
                '  model_provider: "profile"',
                '  model: "gpt-5.4"',
                "  model_providers:",
                "    profile:",
                '      name: "vipnewapi"',
                '      base_url: "https://profile.invalid/v1"',
            ]
        ),
        encoding="utf-8",
    )
    workspace_config.write_text(
        "\n".join(
            [
                "codex:",
                '  model: "gpt-5.5"',
                "  model_providers:",
                "    profile:",
                '      wire_api: "responses"',
                "      requires_openai_auth: true",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("MENTE_HOME", str(mente_home))
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "public-codex-home"))
    captured: dict[str, object] = {}

    class _Runner:
        def run(self, *, payload, session, runtime_config):
            captured["overrides"] = runtime_config.to_codex_overrides()
            captured["config_exists"] = (runtime_config.runtime_home / "config.toml").exists()
            return KernelExecutionResult(status="success", assistant_summary="ok")

    executor = CodexExecutor(codex_binary="codex", runner=_Runner())
    request = ExecutionRequest(
        task_id="task_1",
        session_id="session_1",
        task_type="conversation",
        objective="Reply",
        user_request="Reply to the user",
        workspace=str(workspace),
    )

    result = executor.execute(request)

    assert result.status == "success"
    assert captured["config_exists"] is False
    assert 'model_provider="profile"' in captured["overrides"]
    assert 'model="gpt-5.5"' in captured["overrides"]
    assert 'model_providers.profile.name="vipnewapi"' in captured["overrides"]
    assert 'model_providers.profile.base_url="https://profile.invalid/v1"' in captured["overrides"]
    assert 'model_providers.profile.wire_api="responses"' in captured["overrides"]


def test_codex_executor_emits_runtime_preparation_events(monkeypatch, tmp_path):
    public_codex_home = tmp_path / "public-codex-home"
    public_codex_home.mkdir()
    (public_codex_home / "auth.json").write_text('{"OPENAI_API_KEY":"test-openai-key"}', encoding="utf-8")
    monkeypatch.setenv("CODEX_HOME", str(public_codex_home))

    events: list[tuple[str, dict[str, object]]] = []
    runtime_config = RuntimeConfig(runtime_home=tmp_path / "private-runtime-home")

    class _Runner:
        def run(self, *, payload, session, runtime_config):
            return KernelExecutionResult(status="success", assistant_summary="ok")

    executor = CodexExecutor(
        runner=_Runner(),
        runtime_config=runtime_config,
        memory_repository=InMemoryMemoryRepository(),
        event_callback=lambda event_type, payload: events.append((event_type, payload)),
    )
    request = ExecutionRequest(
        task_id="task_1",
        session_id="session_1",
        task_type="conversation",
        objective="Reply",
        user_request="Reply to the user",
        workspace=str(tmp_path),
    )

    result = executor.execute(request)

    assert result.status == "success"
    assert [event_type for event_type, _payload in events] == [
        "executor.memory_context_resolved",
        "executor.prompt_prepared",
        "executor.runtime_config_resolved",
        "executor.auth_prepared",
    ]
    assert events[0][1]["injected_count"] == 0
    assert events[1][1]["memory_fact_count"] == 0
    assert isinstance(events[1][1]["prompt_fingerprint"], str)
    assert events[2][1]["runtime_home"] == str(runtime_config.runtime_home)
    assert events[3][1]["auth_source"] == "hermes-auth-store"
    assert (runtime_config.runtime_home / "auth.json").exists()


def test_codex_executor_injects_bridge_mcp_runtime_for_gateway_publish_tool(monkeypatch, tmp_path):
    monkeypatch.setenv("MENTE_HOME", str(tmp_path / ".mente"))
    captured: dict[str, object] = {}

    class _Runner:
        def run(self, *, payload, session, runtime_config):
            captured["runtime_config"] = runtime_config
            return KernelExecutionResult(status="success", assistant_summary="ok")

    executor = CodexExecutor(codex_binary="codex", runner=_Runner())
    request = ExecutionRequest(
        task_id="task_1",
        session_id="session_1",
        task_type="conversation",
        objective="Reply",
        user_request="Publish this article to WeChat drafts.",
        workspace=str(tmp_path),
        tool_policy={
            "bridge_tools": ["mente_wechat_publish_draft"],
        },
    )

    result = executor.execute(request)

    assert result.status == "success"
    assert isinstance(captured["runtime_config"], RuntimeConfig)
    overrides = captured["runtime_config"].to_codex_overrides()
    assert 'mcp_servers.mente.args=["-m", "mente.executors.mcp_server"]' in overrides
    assert 'mcp_servers.mente.enabled_tools=["mente_wechat_publish_draft"]' in overrides


def test_codex_executor_execute_delegates_to_kernel_runner(monkeypatch, tmp_path):
    captured: dict[str, object] = {}

    class _Runner:
        def run(self, *, payload, session, runtime_config):
            captured["payload"] = payload
            captured["session"] = session
            captured["runtime_config"] = runtime_config
            return KernelExecutionResult(
                status="success",
                assistant_summary="vendored summary",
                memory_candidates=["persist this"],
                commands_run=["codex exec --ephemeral"],
                changed_files=["report.md"],
                artifacts_out=["report.md", "report.html", "report.docx"],
                verification_results=["checked report files exist"],
                follow_up_tasks=[],
                debug={"returncode": 0, "structured_output": {"assistant_summary": "vendored summary"}},
            )

    monkeypatch.setenv("MENTE_HOME", str(tmp_path / ".mente"))
    executor = CodexExecutor(codex_binary="codex", runner=_Runner())
    request = ExecutionRequest(
        task_id="task_1",
        session_id="session_1",
        task_type="conversation",
        objective="Reply",
        user_request="Reply to the user",
        workspace=str(tmp_path),
    )

    result = executor.execute(request)

    assert isinstance(executor._runner, object)
    assert isinstance(captured["payload"], KernelExecutionPayload)
    assert captured["payload"].prompt == executor.build_prompt(request)
    assert captured["session"].mode is KernelSessionMode.STATELESS
    assert captured["session"].session_id is None
    assert isinstance(captured["runtime_config"], RuntimeConfig)
    assert result.status == "success"
    assert result.summary == "vendored summary"
    assert result.memory_candidates == ["persist this"]
    assert result.commands_run == ["codex exec --ephemeral"]
    assert result.changed_files == ["report.md"]
    assert result.artifacts_out == ["report.md", "report.html", "report.docx"]
    assert result.verification_results == ["checked report files exist"]
    assert result.follow_up_tasks == []
    assert result.metadata["returncode"] == 0


def test_codex_executor_blocks_deep_research_success_without_report_artifacts(tmp_path):
    executor = CodexExecutor(codex_binary="codex")
    request = ExecutionRequest(
        task_id="task_1",
        session_id="session_1",
        task_type="research",
        objective="生成完整深度调研报告",
        user_request="深度研究 BHEB 并形成完整报告",
        workspace=str(tmp_path),
        metadata={"task_profile": "deep_research"},
    )

    translated = executor._translate_kernel_result(
        KernelExecutionResult(
            status="success",
            assistant_summary=(
                "Checked the deep-research skill entrypoint and workflow. "
                "Next I'm running the managed workflow for BHEB."
            ),
            debug={"structured_output": {"assistant_summary": "placeholder"}},
        ),
        request,
        KernelSessionRequest(mode=KernelSessionMode.STATELESS),
    )

    assert translated.status == "blocked"
    assert translated.failure_reason == "deep_research_managed_cli_not_executed"
    assert translated.artifacts_out == []
    assert "未真正执行托管 deep-research CLI" in translated.summary
    assert translated.metadata["deep_research_managed_cli_validation"] == {
        "executed": False,
        "deferred_execution": True,
        "commands_seen": [],
        "managed_cli_commands": [],
        "active_commands": [],
        "active_managed_cli_commands": [],
        "thread_id": None,
    }


def test_codex_executor_accepts_deep_research_paths_extracted_from_summary(tmp_path):
    report_dir = tmp_path / "reports"
    report_dir.mkdir()
    report_md = report_dir / "bheb_report.md"
    report_html = report_dir / "bheb_report.html"
    report_docx = report_dir / "bheb_report.docx"
    for path in (report_md, report_html, report_docx):
        path.write_text("ok", encoding="utf-8")

    executor = CodexExecutor(codex_binary="codex")
    request = ExecutionRequest(
        task_id="task_1",
        session_id="session_1",
        task_type="research",
        objective="生成完整深度调研报告",
        user_request="深度研究 BHEB 并形成完整报告",
        workspace=str(tmp_path),
        metadata={"task_profile": "deep_research"},
    )

    translated = executor._translate_kernel_result(
        KernelExecutionResult(
            status="success",
            assistant_summary=(
                "研究完成。\n"
                f"Markdown: {report_md}\n"
                f"HTML: {report_html}\n"
                f"DOCX: {report_docx}"
            ),
            debug={"structured_output": {"assistant_summary": "placeholder"}},
        ),
        request,
        KernelSessionRequest(mode=KernelSessionMode.STATELESS),
    )

    assert translated.status == "success"
    assert translated.artifacts_out == [
        str(report_md),
        str(report_html),
        str(report_docx),
    ]
    assert translated.failure_reason is None
    assert translated.metadata["deep_research_artifact_validation"] == {
        "validated": True,
        "missing_formats": [],
        "missing_paths": [],
        "candidate_artifacts": [
            str(report_md),
            str(report_html),
            str(report_docx),
        ],
    }


def test_codex_executor_preserves_real_deep_research_blocker_without_artifact_override(tmp_path):
    executor = CodexExecutor(codex_binary="codex")
    request = ExecutionRequest(
        task_id="task_1",
        session_id="session_1",
        task_type="research",
        objective="生成完整深度调研报告",
        user_request="深度研究 BHEB 并形成完整报告",
        workspace=str(tmp_path),
        metadata={"task_profile": "deep_research"},
    )

    translated = executor._translate_kernel_result(
        KernelExecutionResult(
            status="blocked",
            assistant_summary="缺少搜索 API 配置，无法继续生成最终报告。",
            verification_results=["已执行托管 deep research CLI"],
            follow_up_tasks=["配置 TAVILY_API_KEY 或 BRAVE_API_KEY 后重试"],
            debug={
                "structured_output": {
                    "assistant_summary": "缺少搜索 API 配置，无法继续生成最终报告。",
                    "completion_status": "blocked",
                }
            },
        ),
        request,
        KernelSessionRequest(mode=KernelSessionMode.STATELESS),
    )

    assert translated.status == "blocked"
    assert translated.summary == "缺少搜索 API 配置，无法继续生成最终报告。"
    assert translated.follow_up_tasks == ["配置 TAVILY_API_KEY 或 BRAVE_API_KEY 后重试"]
    assert "deep_research_artifact_validation" not in translated.metadata


def test_codex_executor_marks_deep_research_blocked_when_managed_cli_was_not_executed(tmp_path):
    executor = CodexExecutor(codex_binary="codex")
    request = ExecutionRequest(
        task_id="task_1",
        session_id="session_1",
        task_type="research",
        objective="生成完整深度调研报告",
        user_request="深度研究 BHEB 并形成完整报告",
        workspace=str(tmp_path),
        metadata={"task_profile": "deep_research"},
    )
    summary = (
        "Started the managed deep-research workflow by reading the skill instructions and entrypoint. "
        "Next step is to run the provided parallel CLI for the target chemical, then verify "
        "Markdown/HTML/DOCX artifacts under the configured output root."
    )
    stdout = "\n".join(
        [
            json.dumps({"type": "thread.started", "thread_id": "thread-123"}),
            json.dumps(
                {
                    "type": "item.completed",
                    "item": {
                        "id": "item_0",
                        "type": "command_execution",
                        "command": "/bin/bash -lc \"sed -n '1,260p' /home/jason/.mente/skills/research/deep-research-pro/deep_research_pro.py\"",
                        "aggregated_output": "ok",
                        "exit_code": 0,
                        "status": "completed",
                    },
                }
            ),
            json.dumps(
                {
                    "type": "item.completed",
                    "item": {
                        "id": "item_1",
                        "type": "command_execution",
                        "command": "/bin/bash -lc \"sed -n '1,220p' /home/jason/.mente/skills/research/deep-research-pro/SKILL.md\"",
                        "aggregated_output": "ok",
                        "exit_code": 0,
                        "status": "completed",
                    },
                }
            ),
        ]
    )

    translated = executor._translate_kernel_result(
        KernelExecutionResult(
            status="blocked",
            assistant_summary=summary,
            follow_up_tasks=["Run the managed CLI and verify the final artifacts."],
            debug={
                "stdout": stdout,
                "thread_id": "thread-123",
                "structured_output": {
                    "assistant_summary": summary,
                    "completion_status": "blocked",
                    "follow_up_tasks": ["Run the managed CLI and verify the final artifacts."],
                },
            },
        ),
        request,
        KernelSessionRequest(mode=KernelSessionMode.STATELESS),
    )

    assert translated.status == "blocked"
    assert translated.failure_reason == "deep_research_managed_cli_not_executed"
    assert "未真正执行托管 deep-research CLI" in translated.summary
    assert translated.metadata["deep_research_managed_cli_validation"] == {
        "executed": False,
        "deferred_execution": True,
        "commands_seen": [
            "/bin/bash -lc \"sed -n '1,260p' /home/jason/.mente/skills/research/deep-research-pro/deep_research_pro.py\"",
            "/bin/bash -lc \"sed -n '1,220p' /home/jason/.mente/skills/research/deep-research-pro/SKILL.md\"",
        ],
        "managed_cli_commands": [],
        "active_commands": [],
        "active_managed_cli_commands": [],
        "thread_id": "thread-123",
    }


def test_codex_executor_retries_deep_research_once_when_model_only_reads_skill_files(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("MENTE_SESSIONFUL_EXECUTION_ENABLED", "1")
    monkeypatch.setenv("MENTE_SESSIONFUL_EXECUTION_SOURCES", "gateway")
    monkeypatch.setattr(
        CodexExecutor,
        "_should_execute_managed_deep_research_directly",
        lambda self, request: False,
    )

    report_dir = tmp_path / "reports"
    report_dir.mkdir()
    report_md = report_dir / "bheb_report.md"
    report_html = report_dir / "bheb_report.html"
    report_docx = report_dir / "bheb_report.docx"
    for path in (report_md, report_html, report_docx):
        path.write_text("ok", encoding="utf-8")

    calls: list[KernelSessionRequest] = []
    prompts: list[str] = []
    first_summary = (
        "Started the managed deep-research workflow by reading the skill instructions and entrypoint. "
        "Next step is to run the provided parallel CLI for the target chemical."
    )
    first_stdout = "\n".join(
        [
            json.dumps({"type": "thread.started", "thread_id": "thread-123"}),
            json.dumps(
                {
                    "type": "item.completed",
                    "item": {
                        "id": "item_0",
                        "type": "command_execution",
                        "command": "/bin/bash -lc \"sed -n '1,260p' /home/jason/.mente/skills/research/deep-research-pro/deep_research_pro.py\"",
                        "aggregated_output": "ok",
                        "exit_code": 0,
                        "status": "completed",
                    },
                }
            ),
        ]
    )

    class _Runner:
        def run(self, *, payload, session, runtime_config):
            calls.append(session)
            prompts.append(payload.prompt)
            if len(calls) == 1:
                return KernelExecutionResult(
                    status="blocked",
                    assistant_summary=first_summary,
                    follow_up_tasks=["Run the managed CLI and verify the final artifacts."],
                    debug={
                        "stdout": first_stdout,
                        "thread_id": "thread-123",
                        "structured_output": {
                            "assistant_summary": first_summary,
                            "completion_status": "blocked",
                            "follow_up_tasks": ["Run the managed CLI and verify the final artifacts."],
                        },
                    },
                )
            return KernelExecutionResult(
                status="success",
                assistant_summary=(
                    "研究完成。\n"
                    f"Markdown: {report_md}\n"
                    f"HTML: {report_html}\n"
                    f"DOCX: {report_docx}"
                ),
                artifacts_out=[str(report_md), str(report_html), str(report_docx)],
                verification_results=["checked report files exist"],
                debug={
                    "thread_id": "thread-123",
                    "structured_output": {
                        "assistant_summary": "研究完成",
                        "completion_status": "success",
                        "artifacts_out": [str(report_md), str(report_html), str(report_docx)],
                        "verification_results": ["checked report files exist"],
                    },
                },
            )

    executor = CodexExecutor(codex_binary="codex", runner=_Runner())
    request = ExecutionRequest(
        task_id="task_1",
        session_id="session_1",
        task_type="research",
        objective="生成完整深度调研报告",
        user_request="深度研究 BHEB 并形成完整报告",
        workspace=str(tmp_path),
        execution_mode=ExecutionMode.SESSIONFUL,
        execution_session=ExecutionSession(mode=SessionMode.START),
        tool_policy={"session_capable": True},
        metadata={
            "source": "gateway",
            "task_profile": "deep_research",
            "operator_capsule": {
                "skill_entrypoint": "/home/jason/.mente/skills/research/deep-research-pro/deep_research_pro.py",
            },
        },
    )

    result = executor.execute(request)

    assert result.status == "success"
    assert [session.mode for session in calls] == [
        KernelSessionMode.SESSION,
        KernelSessionMode.SESSION,
    ]
    assert calls[1].session_id == "thread-123"
    assert "The previous turn stopped after only reading skill files." in prompts[1]
    assert result.artifacts_out == [str(report_md), str(report_html), str(report_docx)]
    assert result.metadata["deep_research_retry"] == {
        "triggered": True,
        "reason": "managed_cli_not_executed",
        "resumed_thread_id": "thread-123",
    }


def test_codex_executor_retries_skill_audit_once_when_first_turn_only_reads_skill_files(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("MENTE_SESSIONFUL_EXECUTION_ENABLED", "1")
    monkeypatch.setenv("MENTE_SESSIONFUL_EXECUTION_SOURCES", "gateway")

    calls: list[KernelSessionRequest] = []
    prompts: list[str] = []
    first_summary = (
        "先按技能审查模式处理。我已经读了 SKILL.md 并锁定了直接相关的脚本，"
        "下一步会检查这些入口的一致性、健壮性和可维护性，不执行整条工作流。"
    )
    first_stdout = "\n".join(
        [
            json.dumps({"type": "thread.started", "thread_id": "thread-skill-audit"}),
            json.dumps(
                {
                    "type": "item.completed",
                    "item": {
                        "id": "item_0",
                        "type": "command_execution",
                        "command": "/bin/bash -lc \"sed -n '1,220p' /home/jason/.mente/skills/social-media/xhs-daily-news/SKILL.md\"",
                        "aggregated_output": "ok",
                        "exit_code": 0,
                        "status": "completed",
                    },
                }
            ),
            json.dumps(
                {
                    "type": "item.completed",
                    "item": {
                        "id": "item_1",
                        "type": "command_execution",
                        "command": "/bin/bash -lc \"rg -n 'convert_to_xhs|publish' /home/jason/.mente/skills/social-media/xhs-daily-news\"",
                        "aggregated_output": "ok",
                        "exit_code": 0,
                        "status": "completed",
                    },
                }
            ),
        ]
    )

    class _Runner:
        def run(self, *, payload, session, runtime_config):
            calls.append(session)
            prompts.append(payload.prompt)
            if len(calls) == 1:
                return KernelExecutionResult(
                    status="success",
                    assistant_summary=first_summary,
                    follow_up_tasks=["继续检查脚本入口并整理结论。"],
                    debug={
                        "stdout": first_stdout,
                        "thread_id": "thread-skill-audit",
                        "structured_output": {
                            "assistant_summary": first_summary,
                            "completion_status": "success",
                            "follow_up_tasks": ["继续检查脚本入口并整理结论。"],
                        },
                    },
                )
            return KernelExecutionResult(
                status="success",
                assistant_summary=(
                    "发现 2 个高优先级优化项："
                    " [1] convert_to_xhs.py 解析链路对字段变体过于脆弱；"
                    " [2] publish_images.py 的图片选择与顺序规则过于隐式。"
                ),
                verification_results=["checked referenced skill files"],
                debug={
                    "thread_id": "thread-skill-audit",
                    "structured_output": {
                        "assistant_summary": "发现 2 个高优先级优化项",
                        "completion_status": "success",
                        "verification_results": ["checked referenced skill files"],
                    },
                },
            )

    executor = CodexExecutor(codex_binary="codex", runner=_Runner())
    request = ExecutionRequest(
        task_id="task_1",
        session_id="session_1",
        task_type="engineering",
        objective="审查 Daily News 技能并给出优化建议",
        user_request="你帮我看看 daily news 技能，看看有哪些方面需要改进",
        workspace=str(tmp_path),
        execution_mode=ExecutionMode.SESSIONFUL,
        execution_session=ExecutionSession(mode=SessionMode.START),
        tool_policy={"session_capable": True},
        skill_refs=["social-media/xhs-daily-news"],
        metadata={"source": "gateway", "task_profile": "skill_audit", "lane": "engineering"},
    )

    result = executor.execute(request)

    assert result.status == "success"
    assert [session.mode for session in calls] == [
        KernelSessionMode.SESSION,
        KernelSessionMode.SESSION,
    ]
    assert calls[1].session_id == "thread-skill-audit"
    assert "The previous turn stopped after only reading the skill instructions" in prompts[1]
    assert result.metadata["skill_audit_retry"] == {
        "triggered": True,
        "reason": "probe_only_turn",
        "resumed_thread_id": "thread-skill-audit",
    }


def test_codex_executor_retries_deep_research_once_for_probe_only_turn_with_latest_summary_wording(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("MENTE_SESSIONFUL_EXECUTION_ENABLED", "1")
    monkeypatch.setenv("MENTE_SESSIONFUL_EXECUTION_SOURCES", "gateway")
    monkeypatch.setattr(
        CodexExecutor,
        "_should_execute_managed_deep_research_directly",
        lambda self, request: False,
    )

    report_dir = tmp_path / "reports"
    report_dir.mkdir()
    report_md = report_dir / "bheb_report.md"
    report_html = report_dir / "bheb_report.html"
    report_docx = report_dir / "bheb_report.docx"
    for path in (report_md, report_html, report_docx):
        path.write_text("ok", encoding="utf-8")

    calls: list[KernelSessionRequest] = []
    prompts: list[str] = []
    first_summary = (
        "I’m using the managed deep-research skill entrypoint and checking its instructions first, "
        "then I’ll run the full report workflow and verify the generated artifacts."
    )
    first_stdout = "\n".join(
        [
            json.dumps({"type": "thread.started", "thread_id": "thread-123"}),
            json.dumps(
                {
                    "type": "item.completed",
                    "item": {
                        "id": "item_0",
                        "type": "command_execution",
                        "command": "/bin/bash -lc \"sed -n '1,220p' /home/jason/.mente/skills/research/deep-research-pro/SKILL.md\"",
                        "aggregated_output": "ok",
                        "exit_code": 0,
                        "status": "completed",
                    },
                }
            ),
            json.dumps(
                {
                    "type": "item.completed",
                    "item": {
                        "id": "item_1",
                        "type": "command_execution",
                        "command": "/bin/bash -lc \"sed -n '1,260p' /home/jason/.mente/skills/research/deep-research-pro/deep_research_pro.py\"",
                        "aggregated_output": "ok",
                        "exit_code": 0,
                        "status": "completed",
                    },
                }
            ),
        ]
    )

    class _Runner:
        def run(self, *, payload, session, runtime_config):
            calls.append(session)
            prompts.append(payload.prompt)
            if len(calls) == 1:
                return KernelExecutionResult(
                    status="blocked",
                    assistant_summary=first_summary,
                    follow_up_tasks=[],
                    debug={
                        "stdout": first_stdout,
                        "thread_id": "thread-123",
                        "structured_output": {
                            "assistant_summary": first_summary,
                            "completion_status": "blocked",
                            "follow_up_tasks": [],
                        },
                    },
                )
            return KernelExecutionResult(
                status="success",
                assistant_summary=(
                    "研究完成。\n"
                    f"Markdown: {report_md}\n"
                    f"HTML: {report_html}\n"
                    f"DOCX: {report_docx}"
                ),
                artifacts_out=[str(report_md), str(report_html), str(report_docx)],
                verification_results=["checked report files exist"],
                debug={
                    "thread_id": "thread-123",
                    "structured_output": {
                        "assistant_summary": "研究完成",
                        "completion_status": "success",
                        "artifacts_out": [str(report_md), str(report_html), str(report_docx)],
                        "verification_results": ["checked report files exist"],
                    },
                },
            )

    executor = CodexExecutor(codex_binary="codex", runner=_Runner())
    request = ExecutionRequest(
        task_id="task_1",
        session_id="session_1",
        task_type="research",
        objective="生成完整深度调研报告",
        user_request="调用技能，深度研究抗氧基BHEB 2,6-二叔丁基-4-乙基苯酚这一个标准化学品，形成万字调研报告。",
        workspace=str(tmp_path),
        execution_mode=ExecutionMode.SESSIONFUL,
        execution_session=ExecutionSession(mode=SessionMode.START),
        tool_policy={"session_capable": True},
        metadata={
            "source": "gateway",
            "task_profile": "deep_research",
            "operator_capsule": {
                "skill_entrypoint": "/home/jason/.mente/skills/research/deep-research-pro/deep_research_pro.py",
            },
        },
    )

    result = executor.execute(request)

    assert result.status == "success"
    assert [session.mode for session in calls] == [
        KernelSessionMode.SESSION,
        KernelSessionMode.SESSION,
    ]
    assert calls[1].session_id == "thread-123"
    assert "The previous turn stopped after only reading skill files." in prompts[1]
    assert result.artifacts_out == [str(report_md), str(report_html), str(report_docx)]
    assert result.metadata["deep_research_retry"] == {
        "triggered": True,
        "reason": "managed_cli_not_executed",
        "resumed_thread_id": "thread-123",
    }


def test_codex_executor_retries_deep_research_once_when_managed_cli_is_still_running(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("MENTE_SESSIONFUL_EXECUTION_ENABLED", "1")
    monkeypatch.setenv("MENTE_SESSIONFUL_EXECUTION_SOURCES", "gateway")
    monkeypatch.setattr(
        CodexExecutor,
        "_should_execute_managed_deep_research_directly",
        lambda self, request: False,
    )

    report_dir = tmp_path / "reports"
    report_dir.mkdir()
    report_md = report_dir / "bheb_report.md"
    report_html = report_dir / "bheb_report.html"
    report_docx = report_dir / "bheb_report.docx"
    for path in (report_md, report_html, report_docx):
        path.write_text("ok", encoding="utf-8")

    calls: list[KernelSessionRequest] = []
    prompts: list[str] = []
    first_summary = (
        "已按技能要求启动受管深度研究工作流，正在生成关于“抗氧基BHEB 2,6-二叔丁基-4-乙基苯酚”的完整调研报告。"
        "下一步是等待工作流完成并核验 Markdown、HTML、DOCX 三种产物是否落盘。"
    )
    first_stdout = "\n".join(
        [
            json.dumps({"type": "thread.started", "thread_id": "thread-123"}),
            json.dumps(
                {
                    "type": "item.started",
                    "item": {
                        "id": "item_0",
                        "type": "command_execution",
                        "command": (
                            "/bin/bash -lc "
                            "\"python /home/jason/.mente/skills/research/deep-research-pro/"
                            "deep_research_pro.py "
                            "\\\"抗氧基BHEB 2,6-二叔丁基-4-乙基苯酚\\\" "
                            "--output-dir /home/jason/clawd/deep-research\""
                        ),
                        "status": "in_progress",
                    },
                }
            ),
        ]
    )

    class _Runner:
        def run(self, *, payload, session, runtime_config):
            calls.append(session)
            prompts.append(payload.prompt)
            if len(calls) == 1:
                return KernelExecutionResult(
                    status="blocked",
                    assistant_summary=first_summary,
                    follow_up_tasks=["等待工作流完成并核验 Markdown、HTML、DOCX 三种产物是否落盘。"],
                    debug={
                        "stdout": first_stdout,
                        "thread_id": "thread-123",
                        "structured_output": {
                            "assistant_summary": first_summary,
                            "completion_status": "blocked",
                            "follow_up_tasks": ["等待工作流完成并核验 Markdown、HTML、DOCX 三种产物是否落盘。"],
                        },
                    },
                )
            return KernelExecutionResult(
                status="success",
                assistant_summary=(
                    "研究完成。\n"
                    f"Markdown: {report_md}\n"
                    f"HTML: {report_html}\n"
                    f"DOCX: {report_docx}"
                ),
                artifacts_out=[str(report_md), str(report_html), str(report_docx)],
                verification_results=["checked report files exist"],
                debug={
                    "thread_id": "thread-123",
                    "structured_output": {
                        "assistant_summary": "研究完成",
                        "completion_status": "success",
                        "artifacts_out": [str(report_md), str(report_html), str(report_docx)],
                        "verification_results": ["checked report files exist"],
                    },
                },
            )

    executor = CodexExecutor(codex_binary="codex", runner=_Runner())
    request = ExecutionRequest(
        task_id="task_1",
        session_id="session_1",
        task_type="research",
        objective="生成完整深度调研报告",
        user_request="调用技能，深度研究抗氧基BHEB 2,6-二叔丁基-4-乙基苯酚这一个标准化学品，形成万字调研报告。",
        workspace=str(tmp_path),
        execution_mode=ExecutionMode.SESSIONFUL,
        execution_session=ExecutionSession(mode=SessionMode.START),
        tool_policy={"session_capable": True},
        metadata={
            "source": "gateway",
            "task_profile": "deep_research",
            "operator_capsule": {
                "skill_entrypoint": "/home/jason/.mente/skills/research/deep-research-pro/deep_research_pro.py",
            },
        },
    )

    result = executor.execute(request)

    assert result.status == "success"
    assert [session.mode for session in calls] == [
        KernelSessionMode.SESSION,
        KernelSessionMode.SESSION,
    ]
    assert calls[1].session_id == "thread-123"
    assert "The previous turn already launched the managed deep-research CLI" in prompts[1]
    assert "Do not stop while the managed CLI command is still running." in prompts[1]
    assert result.artifacts_out == [str(report_md), str(report_html), str(report_docx)]
    assert result.metadata["deep_research_retry"] == {
        "triggered": True,
        "reason": "managed_cli_still_running",
        "resumed_thread_id": "thread-123",
    }


def test_codex_executor_runs_deep_research_via_managed_cli_directly_and_bypasses_runner(
    monkeypatch, tmp_path
):
    mente_home = tmp_path / ".mente"
    mente_home.mkdir()
    (mente_home / "config.yaml").write_text(
        f"mente:\n  deep_research:\n    output_root: {tmp_path}\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("MENTE_HOME", str(mente_home))

    report_dir = tmp_path / "reports"
    report_dir.mkdir()
    report_md = report_dir / "bheb_report.md"
    report_html = report_dir / "bheb_report.html"
    report_docx = report_dir / "bheb_report.docx"
    for path in (report_md, report_html, report_docx):
        path.write_text("ok", encoding="utf-8")

    captured: dict[str, object] = {}

    def _fake_subprocess_run(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        stdout = (
            "研究完成: 抗氧基BHEB 2,6-二叔丁基-4-乙基苯酚\n"
            "并行 workers: 3\n"
            f"Markdown: {report_md}\n"
            f"HTML: {report_html}\n"
            f"DOCX: {report_docx}\n"
        )
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")

    monkeypatch.setattr("mente.executors.codex.subprocess.run", _fake_subprocess_run)

    class _Runner:
        def run(self, *, payload, session, runtime_config):
            raise AssertionError("deep research should bypass the Codex runner")

    runtime_config = RuntimeConfig(
        runtime_home=tmp_path / "runtime-home",
        model_runtime=ModelRuntime(
            model="gpt-5.4",
            provider="newapi",
            base_url="https://newapi.10fu.com/v1",
            api_mode="chat_completions",
            source="test",
        ),
        subprocess_env={},
    )
    executor = CodexExecutor(
        codex_binary="codex",
        runner=_Runner(),
        runtime_config=runtime_config,
    )
    request = ExecutionRequest(
        task_id="task_1",
        session_id="session_1",
        task_type="research",
        objective="生成完整深度调研报告",
        user_request="调用技能，深度研究抗氧基BHEB 2,6-二叔丁基-4-乙基苯酚这一个标准化学品，形成万字调研报告。",
        workspace=str(tmp_path),
        metadata={
            "source": "gateway",
            "lane": "research",
            "task_profile": "deep_research",
            "operator_capsule": {
                "skill_entrypoint": "/home/jason/.mente/skills/research/deep-research-pro/deep_research_pro.py",
            },
        },
        skill_refs=["research/deep-research-pro"],
    )

    result = executor.execute(request)

    assert result.status == "success"
    assert result.artifacts_out == [str(report_md), str(report_html), str(report_docx)]
    assert result.metadata["managed_skill_execution"] == {
        "mode": "direct_subprocess",
        "command": [
            captured["command"][0],
            "/home/jason/.mente/skills/research/deep-research-pro/deep_research_pro.py",
            "抗氧基BHEB 2,6-二叔丁基-4-乙基苯酚",
            "--output-dir",
            str(tmp_path),
        ],
        "returncode": 0,
    }
    assert captured["kwargs"]["cwd"] == str(tmp_path)
    assert captured["kwargs"]["text"] is True
    assert captured["kwargs"]["capture_output"] is True


@pytest.mark.parametrize(
    ("user_request", "assistant_summary", "model_runtime", "expected_summary"),
    [
        (
            "你是谁",
            "我是 Codex，一个在这台机器上帮你处理代码、文件、命令行任务和一般问题的 AI 助手。",
            None,
            "我是 Mente，一个在这台机器上帮你处理代码、文件、命令行任务和一般问题的 AI 助手。",
        ),
        (
            "Who are you?",
            "I am Codex, an AI assistant on this machine.",
            None,
            "I am Mente, an AI assistant on this machine.",
        ),
        (
            "你好",
            "我是 Mente，一个基于 GPT-5 的 AI 助手，主要帮你写代码、排查问题、查资料和处理各种任务。",
            None,
            "我是 Mente，一个在这台机器上帮你处理代码、文件、命令行任务和一般问题的 AI 助手。",
        ),
        (
            "你好",
            "我是 Mente，你的智能 AI 助手。\n我可以直接帮你做这些事：\n- 查资料、做调研\n- 读写代码、排查问题",
            None,
            "我是 Mente，一个在这台机器上帮你处理代码、文件、命令行任务和一般问题的 AI 助手。",
        ),
        (
            "继续",
            "⏳ Mente 正在执行\n1. 🚀 正在调用 Codex runtime\n2. 🤖 Codex 已开始执行\n3. 🧮 Codex 回合完成\n4. 📨 Codex runtime 已返回",
            None,
            "⏳ Mente 正在执行\n1. 🚀 正在调用 Mente runtime\n2. 🤖 Mente 已开始执行\n3. 🧮 Mente 回合完成\n4. 📨 Mente runtime 已返回",
        ),
        (
            "你是谁",
            "runtime_not_bootstrapped:vendored runtime artifact is not bootstrapped for this Mente release; expected /root/code/Mente/kernel/codex/release/artifacts/linux-x86_64/codex. public codex fallback is disabled.",
            None,
            "runtime_not_bootstrapped:vendored runtime artifact is not bootstrapped for this Mente release; expected /root/code/Mente/kernel/codex/release/artifacts/linux-x86_64/codex. public runtime fallback is disabled.",
        ),
        (
            "你是什么大模型",
            "我是 Claude，由 Anthropic 开发的大语言模型。当前运行在 Mente CLI 环境中，可以通过工具帮你执行代码、操作文件、搜索信息等任务。有什么需要帮忙的？",
            ModelRuntime(
                model="mimo-v2.5-pro",
                provider="xiaomi",
                base_url="https://token-plan-cn.xiaomimimo.com/anthropic",
                api_mode="anthropic_messages",
                source="mente_model_settings",
            ),
            "我是 Mente，当前接入的模型是 mimo-v2.5-pro。我可以通过工具帮你执行代码、操作文件、搜索信息等任务。",
        ),
        (
            "你是什么大模型",
            "我是基于 OpenAI GPT 系列大模型的 Codex CLI 智能编码助手。当前会话中可以通过 `spawn_agent` 调用多个模型变体，包括：\n\n- **GPT-5.5** — 前沿模型，适合复杂编码与研究任务\n- **GPT-5.4** — 日常编码的主力模型\n- **GPT-5.4-Mini** — 轻量快速，适合简单任务\n- **GPT-5.3-Codex** — 编码优化模型\n- **GPT-5.2** — 面向专业工作和长时运行 Agent\n\n我本身运行在 **Mente** 平台上，可以通过飞书、微信等渠道与你交互，还能连接各种工具和技能来帮你完成任务。有什么需要帮忙的？",
            ModelRuntime(
                model="mimo-v2.5-pro",
                provider="xiaomi",
                base_url="https://token-plan-cn.xiaomimimo.com/anthropic",
                api_mode="anthropic_messages",
                source="mente_model_settings",
            ),
            "我是 Mente，当前接入的模型是 mimo-v2.5-pro。我可以通过工具帮你执行代码、操作文件、搜索信息等任务。",
        ),
    ],
)
def test_codex_executor_normalizes_user_facing_codex_identity(
    monkeypatch, tmp_path, user_request, assistant_summary, model_runtime, expected_summary
):
    monkeypatch.setenv("MENTE_HOME", str(tmp_path / ".mente"))

    class _Runner:
        def run(self, *, payload, session, runtime_config):
            return KernelExecutionResult(status="success", assistant_summary=assistant_summary)

    if model_runtime is not None:
        @contextmanager
        def _fake_bridge(*, model_runtime, api_key):
            yield "http://127.0.0.1:8765/v1"

        monkeypatch.setattr(
            "mente.executors.codex.start_responses_compat_bridge",
            _fake_bridge,
        )

    executor = CodexExecutor(
        codex_binary="codex",
        runner=_Runner(),
        runtime_config=RuntimeConfig(
            runtime_home=tmp_path / ".mente" / "codex",
            model_runtime=model_runtime or ModelRuntime(),
            subprocess_env=(
                {"MENTE_CODEX_API_KEY": "sk-test-xiaomi"}
                if model_runtime is not None
                else {}
            ),
        ),
    )
    request = ExecutionRequest(
        task_id="task_1",
        session_id="session_1",
        task_type="conversation",
        objective="Reply",
        user_request=user_request,
        workspace=str(tmp_path),
    )

    result = executor.execute(request)

    assert result.summary == expected_summary


def test_codex_executor_execute_translates_kernel_failures(monkeypatch, tmp_path):
    monkeypatch.setenv("MENTE_HOME", str(tmp_path / ".mente"))

    class _Runner:
        def run(self, *, payload, session, runtime_config):
            return KernelExecutionResult(
                status="failed",
                assistant_summary="Kernel session mode is recognized but not enabled for production execution yet.",
                commands_run=["codex exec --ephemeral"],
                debug={"session_mode": "session"},
                backend_failure="unsupported_session_mode",
            )

    executor = CodexExecutor(codex_binary="codex", runner=_Runner())
    request = ExecutionRequest(
        task_id="task_1",
        session_id="session_1",
        task_type="conversation",
        objective="Reply",
        user_request="Reply to the user",
        workspace=str(tmp_path),
        execution_mode="session",
        resume_token="resume-123",
    )

    result = executor.execute(request)

    assert result.status == "failed"
    assert result.summary.startswith("Kernel session mode")
    assert result.failure_reason == "unsupported_session_mode"
    assert result.metadata["session_mode"] == "session"


def test_codex_executor_bridges_non_responses_model_runtime(monkeypatch, tmp_path):
    monkeypatch.setenv("MENTE_HOME", str(tmp_path / ".mente"))
    captured: dict[str, object] = {}

    class _Runner:
        def run(self, *, payload, session, runtime_config):
            captured["runtime_config"] = runtime_config
            return KernelExecutionResult(status="success", assistant_summary="bridged ok")

    @contextmanager
    def _fake_bridge(*, model_runtime, api_key):
        assert model_runtime.api_mode == "anthropic_messages"
        assert api_key == "sk-test-xiaomi"
        yield "http://127.0.0.1:8765/v1"

    monkeypatch.setattr(
        "mente.executors.codex.start_responses_compat_bridge",
        _fake_bridge,
    )

    runtime_config = RuntimeConfig(
        runtime_home=tmp_path / ".mente" / "codex",
        model_runtime=ModelRuntime(
            model="mimo-v2.5-pro",
            provider="xiaomi",
            base_url="https://token-plan-cn.xiaomimimo.com/anthropic",
            api_mode="anthropic_messages",
            source="mente_model_settings",
        ),
        subprocess_env={"MENTE_CODEX_API_KEY": "sk-test-xiaomi"},
    )
    executor = CodexExecutor(codex_binary="codex", runtime_config=runtime_config, runner=_Runner())
    request = ExecutionRequest(
        task_id="task_1",
        session_id="session_1",
        task_type="conversation",
        objective="Reply",
        user_request="hello，你是谁？",
        workspace=str(tmp_path),
    )

    result = executor.execute(request)

    bridged_runtime_config = captured["runtime_config"]
    assert isinstance(bridged_runtime_config, RuntimeConfig)
    assert result.status == "success"
    assert result.summary == "bridged ok"
    assert bridged_runtime_config.codex_config["model_provider"] == "mente_bridge"
    assert bridged_runtime_config.codex_config["model_providers"]["mente_bridge"]["base_url"] == (
        "http://127.0.0.1:8765/v1"
    )
    assert bridged_runtime_config.codex_config["model_providers"]["mente_bridge"]["wire_api"] == (
        "responses"
    )
    assert bridged_runtime_config.subprocess_env["MENTE_CODEX_API_KEY"] == "sk-test-xiaomi"


def test_codex_executor_collapses_machine_failure_dump_to_concise_summary(monkeypatch, tmp_path):
    monkeypatch.setenv("MENTE_HOME", str(tmp_path / ".mente"))

    machine_dump = "\n".join(
        [
            '{"type":"thread.started","thread_id":"thread-123"}',
            '{"type":"turn.started"}',
            '{"type":"turn.failed","error":{"message":"cancelled"}}',
        ]
    )

    class _Runner:
        def run(self, *, payload, session, runtime_config):
            return KernelExecutionResult(
                status="failed",
                assistant_summary=machine_dump,
                backend_failure="interrupted_by_user",
            )

    executor = CodexExecutor(codex_binary="codex", runner=_Runner())
    request = ExecutionRequest(
        task_id="task_1",
        session_id="session_1",
        task_type="conversation",
        objective="Reply",
        user_request="为什么没有发布成功？",
        workspace=str(tmp_path),
    )

    result = executor.execute(request)

    assert result.status == "failed"
    assert result.summary == "任务已取消。"
    assert result.failure_reason == "interrupted_by_user"


def test_codex_executor_surfaces_failure_message_from_machine_dump(monkeypatch, tmp_path):
    monkeypatch.setenv("MENTE_HOME", str(tmp_path / ".mente"))

    machine_dump = "\n".join(
        [
            '{"type":"thread.started","thread_id":"thread-123"}',
            '{"type":"turn.started"}',
            '{"type":"error","message":"Reconnecting... 1/5 (stream disconnected before completion: AuthenticationError: Error code: 401 - invalid_key)"}',
            '{"type":"turn.failed","error":{"message":"stream disconnected before completion: AuthenticationError: Error code: 401 - invalid_key"}}',
        ]
    )

    class _Runner:
        def run(self, *, payload, session, runtime_config):
            return KernelExecutionResult(
                status="failed",
                assistant_summary=machine_dump,
                backend_failure="exit_code:1",
            )

    executor = CodexExecutor(codex_binary="codex", runner=_Runner())
    request = ExecutionRequest(
        task_id="task_1",
        session_id="session_1",
        task_type="conversation",
        objective="Reply",
        user_request="hello，你是谁？",
        workspace=str(tmp_path),
    )

    result = executor.execute(request)

    assert result.status == "failed"
    assert result.summary == (
        "stream disconnected before completion: AuthenticationError: Error code: 401 - invalid_key"
    )
    assert result.failure_reason == "exit_code:1"


def test_codex_executor_build_command_delegates_to_vendored_launcher(monkeypatch):
    executor = CodexExecutor(codex_binary="codex")
    request = ExecutionRequest(
        task_id="task_1",
        session_id="session_1",
        task_type="conversation",
        objective="Reply",
        user_request="Reply to the user",
        workspace=".",
    )
    captured: dict[str, object] = {}

    def fake_build_vendored_command(**kwargs):
        captured.update(kwargs)
        return ["codex", "exec", "--ephemeral", "Reply"]

    monkeypatch.setattr("mente.executors.codex.build_vendored_command", fake_build_vendored_command)

    command = executor.build_command(request, output_schema="schema.json")

    assert command == ["codex", "exec", "--ephemeral", "Reply"]
    assert isinstance(captured["payload"], KernelExecutionPayload)
    assert captured["session"].mode is KernelSessionMode.STATELESS
    assert captured["output_schema"] == "schema.json"



def test_codex_executor_default_command_uses_vendored_bridge_front_door(monkeypatch, tmp_path):
    executor = CodexExecutor()
    fake_runtime = tmp_path / "runtime" / "codex"
    fake_runtime.parent.mkdir(parents=True)
    fake_runtime.write_text("#!/bin/sh\n", encoding="utf-8")
    fake_runtime.chmod(0o755)
    monkeypatch.setenv("MENTE_CODEX_RUNTIME_BIN", str(fake_runtime))
    request = ExecutionRequest(
        task_id="task_1",
        session_id="session_1",
        task_type="engineering",
        objective="Inspect repository",
        user_request="inspect repository",
        workspace=".",
    )

    cmd = executor.build_command(request, output_schema="schema.json")

    assert cmd[0] == str(fake_runtime)
    assert cmd[0] != "codex"


def test_codex_executor_build_command_delegates_to_bridge_call_contract(monkeypatch):
    executor = CodexExecutor()
    request = ExecutionRequest(
        task_id="task_1",
        session_id="session_1",
        task_type="conversation",
        objective="Reply",
        user_request="Reply to the user",
        workspace=".",
    )
    captured: dict[str, object] = {}

    def fake_build_vendored_command(**kwargs):
        captured.update(kwargs)
        return ["/vendored/codex", "exec", "--ephemeral", "Reply"]

    monkeypatch.setattr(
        "mente.executors.codex.build_vendored_command",
        fake_build_vendored_command,
        raising=False,
    )

    command = executor.build_command(request, output_schema="schema.json")

    assert command == ["/vendored/codex", "exec", "--ephemeral", "Reply"]
    assert isinstance(captured["payload"], KernelExecutionPayload)
    assert captured["session"].mode is KernelSessionMode.STATELESS
    assert captured["output_schema"] == "schema.json"
