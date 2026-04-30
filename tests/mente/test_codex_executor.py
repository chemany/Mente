import json
import os
from pathlib import Path

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
from mente.task_core.models import ExecutionRequest


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
    assert any("Inspect repository" in part for part in cmd)

    schema_arg = cmd[cmd.index("--output-schema") + 1]
    assert schema_arg.endswith(".json")


def test_vendored_launcher_matches_codex_executor_command_and_env():
    executor = CodexExecutor(codex_binary="codex")
    request = ExecutionRequest(
        task_id="task_1",
        session_id="session_1",
        task_type="engineering",
        objective="Inspect repository",
        user_request="inspect repository",
        workspace="/workspace/repo",
    )
    runtime_config = RuntimeConfig(
        runtime_home=Path("/private/codex-home"),
        codex_config={"model": "gpt-5.5"},
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
    assert build_private_runtime_env(Path("/private/codex-home")) == executor._build_subprocess_env(
        Path("/private/codex-home")
    )


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
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / ".hermes"))
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
    assert captured["payload"].workspace == str(tmp_path)
    assert captured["session"].mode is KernelSessionMode.STATELESS


def test_codex_executor_execute_seeds_auth_without_copying_shared_state(monkeypatch, tmp_path):
    public_codex_home = tmp_path / "public-codex-home"
    public_codex_home.mkdir()
    (public_codex_home / "auth.json").write_text(
        json.dumps({"OPENAI_API_KEY": "test-openai-key"}),
        encoding="utf-8",
    )
    (public_codex_home / "config.toml").write_text('model = "gpt-5"', encoding="utf-8")
    (public_codex_home / "rules").mkdir()
    (public_codex_home / "rules" / "default.rules").write_text("never share", encoding="utf-8")
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
    assert captured["auth_payload"] == {"OPENAI_API_KEY": "test-openai-key"}
    assert captured["config_exists"] is False
    assert captured["rules_exist"] is False


def test_codex_executor_execute_passes_minimal_provider_overrides_without_copying_config(
    monkeypatch, tmp_path
):
    hermes_home = tmp_path / ".hermes"
    profile_config = hermes_home / "mente" / "config.toml"
    workspace_config = tmp_path / ".mente" / "codex.toml"
    profile_config.parent.mkdir(parents=True, exist_ok=True)
    workspace_config.parent.mkdir(parents=True, exist_ok=True)
    profile_config.write_text(
        "\n".join(
            [
                'model_provider = "profile"',
                'model = "gpt-5.4"',
                "",
                "[model_providers.profile]",
                'name = "vipnewapi"',
                'base_url = "https://profile.invalid/v1"',
            ]
        ),
        encoding="utf-8",
    )
    workspace_config.write_text(
        "\n".join(
            [
                'model = "gpt-5.5"',
                "",
                "[model_providers.profile]",
                'wire_api = "responses"',
                "requires_openai_auth = true",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
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
        workspace=str(tmp_path),
    )

    result = executor.execute(request)

    assert result.status == "success"
    assert captured["config_exists"] is False
    assert 'model_provider="profile"' in captured["overrides"]
    assert 'model="gpt-5.5"' in captured["overrides"]
    assert 'model_providers.profile.name="vipnewapi"' in captured["overrides"]
    assert 'model_providers.profile.base_url="https://profile.invalid/v1"' in captured["overrides"]
    assert 'model_providers.profile.wire_api="responses"' in captured["overrides"]
    assert "model_providers.profile.requires_openai_auth=true" in captured["overrides"]


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

    monkeypatch.setenv("HERMES_HOME", str(tmp_path / ".hermes"))
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
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / ".hermes"))

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

    def fake_build_stateless_command(**kwargs):
        captured.update(kwargs)
        return ["codex", "exec", "--ephemeral", "Reply"]

    monkeypatch.setattr("mente.executors.codex.build_stateless_command", fake_build_stateless_command)

    command = executor.build_command(request, output_schema="schema.json")

    assert command == ["codex", "exec", "--ephemeral", "Reply"]
    assert isinstance(captured["payload"], KernelExecutionPayload)
    assert captured["session"].mode is KernelSessionMode.STATELESS
    assert captured["output_schema"] == "schema.json"
