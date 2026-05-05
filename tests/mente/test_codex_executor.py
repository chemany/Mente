import json
import os
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
from mente.executors.prompting import build_prompt_fingerprint, render_execution_prompt
from mente.executors.runtime_config import RuntimeConfig
from mente.executors.codex import CodexExecutor
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
        tool_policy={"session_capable": True},
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
        tool_policy={"session_capable": True},
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
        "native_tool_source": None,
        "bridge_tool_source": None,
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

    assert "Memory Facts:" in prompt
    assert "assistant_summary" in prompt
    assert "memory_candidates" in prompt
    assert fingerprint == build_prompt_fingerprint(prompt)
    assert len(fingerprint) == 64


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

    assert "Memory Facts:" not in prompt
    assert "If no memory facts are provided" in prompt
    assert "do not fabricate prior user preferences" in prompt


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
    monkeypatch.setenv("MENTE_HOME", str(tmp_path / ".mente"))
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
    assert runtime_config.runtime_home == resolve_runtime_home()
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
        tool_policy={"session_capable": True},
        metadata={"source": "api_server"},
    )

    result = executor.execute(request)

    assert result.status == "success"
    assert "Memory: User prefers concise replies." in captured["payload"].prompt
    assert captured["session"].mode is KernelSessionMode.SESSION


def test_codex_executor_exposes_mente_user_skills_inside_private_runtime(monkeypatch, tmp_path):
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
            linked_skill = (
                runtime_config.runtime_home
                / ".agents"
                / "skills"
                / "media"
                / "wechat-publisher"
                / "SKILL.md"
            )
            captured["linked_skill_exists"] = linked_skill.exists()
            captured["linked_skill_contents"] = linked_skill.read_text(encoding="utf-8")
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
    assert captured["linked_skill_exists"] is True
    assert "wechat-publisher" in captured["linked_skill_contents"]


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
        "executor.runtime_config_resolved",
        "executor.auth_prepared",
    ]
    assert events[0][1]["injected_count"] == 0
    assert events[1][1]["runtime_home"] == str(runtime_config.runtime_home)
    assert events[2][1]["auth_source"] == "hermes-auth-store"
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
    assert result.metadata["returncode"] == 0


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
