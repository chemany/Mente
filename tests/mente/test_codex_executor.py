import json
import os
import subprocess

from mente.executors.prompting import build_prompt_fingerprint, render_execution_prompt
from mente.executors.codex import CodexExecutor
from mente.task_core.models import ExecutionRequest


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
    executor = CodexExecutor(codex_binary="codex")
    request = ExecutionRequest(
        task_id="task_1",
        session_id="session_1",
        task_type="conversation",
        objective="Reply",
        user_request="Reply to the user",
        workspace=str(tmp_path),
    )
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "public-codex-home"))
    captured: dict[str, object] = {}

    def fake_run(command, capture_output, text, cwd, check, env):
        output_path = command[command.index("--output-last-message") + 1]
        captured["env"] = env
        captured["cwd"] = cwd
        captured["command"] = command
        captured["codex_home_exists_during_run"] = os.path.isdir(env["CODEX_HOME"])
        with open(output_path, "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "assistant_summary": "ok",
                    "memory_candidates": [],
                },
                handle,
            )
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr("mente.executors.codex.subprocess.run", fake_run)

    result = executor.execute(request)

    assert result.status == "success"
    env = captured["env"]
    assert isinstance(env, dict)
    assert env["CODEX_HOME"] != os.environ["CODEX_HOME"]
    assert os.path.basename(env["CODEX_HOME"]).startswith("mente-codex-home-")
    assert env["HOME"] == env["CODEX_HOME"]
    assert captured["codex_home_exists_during_run"] is True
    assert captured["cwd"] == str(tmp_path)
    command = captured["command"]
    isolated_workdir = command[command.index("--cd") + 1]
    assert isolated_workdir != str(tmp_path)
    assert os.path.basename(isolated_workdir).startswith("mente-codex-workdir-")
    assert command[command.index("--add-dir") + 1] == str(tmp_path)


def test_codex_executor_execute_seeds_auth_without_copying_shared_state(monkeypatch, tmp_path):
    executor = CodexExecutor(codex_binary="codex")
    request = ExecutionRequest(
        task_id="task_1",
        session_id="session_1",
        task_type="conversation",
        objective="Reply",
        user_request="Reply to the user",
        workspace=str(tmp_path),
    )
    public_codex_home = tmp_path / "public-codex-home"
    public_codex_home.mkdir()
    (public_codex_home / "auth.json").write_text(
        json.dumps({"OPENAI_API_KEY": "test-openai-key"}),
        encoding="utf-8",
    )
    (public_codex_home / "config.toml").write_text("model = \"gpt-5\"", encoding="utf-8")
    (public_codex_home / "rules").mkdir()
    (public_codex_home / "rules" / "default.rules").write_text("never share", encoding="utf-8")
    monkeypatch.setenv("CODEX_HOME", str(public_codex_home))
    captured: dict[str, object] = {}

    def fake_run(command, capture_output, text, cwd, check, env):
        isolated_home = os.path.realpath(env["CODEX_HOME"])
        output_path = command[command.index("--output-last-message") + 1]
        captured["auth_payload"] = json.loads(
            open(os.path.join(isolated_home, "auth.json"), encoding="utf-8").read()
        )
        captured["config_exists"] = os.path.exists(os.path.join(isolated_home, "config.toml"))
        captured["rules_exist"] = os.path.exists(os.path.join(isolated_home, "rules", "default.rules"))
        with open(output_path, "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "assistant_summary": "ok",
                    "memory_candidates": [],
                },
                handle,
            )
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr("mente.executors.codex.subprocess.run", fake_run)

    result = executor.execute(request)

    assert result.status == "success"
    assert captured["auth_payload"] == {"OPENAI_API_KEY": "test-openai-key"}
    assert captured["config_exists"] is False
    assert captured["rules_exist"] is False


def test_codex_executor_execute_passes_minimal_provider_overrides_without_copying_config(
    monkeypatch, tmp_path
):
    executor = CodexExecutor(codex_binary="codex")
    request = ExecutionRequest(
        task_id="task_1",
        session_id="session_1",
        task_type="conversation",
        objective="Reply",
        user_request="Reply to the user",
        workspace=str(tmp_path),
    )
    public_codex_home = tmp_path / "public-codex-home"
    public_codex_home.mkdir()
    (public_codex_home / "auth.json").write_text(
        json.dumps({"OPENAI_API_KEY": "test-openai-key"}),
        encoding="utf-8",
    )
    (public_codex_home / "config.toml").write_text(
        "\n".join(
            [
                'model_provider = "custom"',
                'model = "gpt-5.4"',
                "",
                "[model_providers.custom]",
                'name = "vipnewapi"',
                'base_url = "https://example.invalid/v1"',
                'wire_api = "responses"',
                "requires_openai_auth = true",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("CODEX_HOME", str(public_codex_home))
    captured: dict[str, object] = {}

    def fake_run(command, capture_output, text, cwd, check, env):
        isolated_home = os.path.realpath(env["CODEX_HOME"])
        output_path = command[command.index("--output-last-message") + 1]
        captured["command"] = command
        captured["config_exists"] = os.path.exists(os.path.join(isolated_home, "config.toml"))
        with open(output_path, "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "assistant_summary": "ok",
                    "memory_candidates": [],
                },
                handle,
            )
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr("mente.executors.codex.subprocess.run", fake_run)

    result = executor.execute(request)

    assert result.status == "success"
    assert captured["config_exists"] is False
    command = captured["command"]
    assert "-c" in command
    config_args = [
        command[index + 1]
        for index, part in enumerate(command[:-1])
        if part == "-c"
    ]
    assert 'model_provider="custom"' in config_args
    assert 'model="gpt-5.4"' in config_args
    assert 'model_providers.custom.name="vipnewapi"' in config_args
    assert 'model_providers.custom.base_url="https://example.invalid/v1"' in config_args
    assert 'model_providers.custom.wire_api="responses"' in config_args
    assert "model_providers.custom.requires_openai_auth=true" in config_args


def test_codex_executor_execute_parses_structured_memory_candidate_output(monkeypatch):
    executor = CodexExecutor(codex_binary="codex")
    request = ExecutionRequest(
        task_id="task_1",
        session_id="session_1",
        task_type="conversation",
        objective="Reply",
        user_request="Reply to the user",
        workspace=".",
    )

    def fake_run(command, capture_output, text, cwd, check, env):
        output_path = command[command.index("--output-last-message") + 1]
        schema_path = command[command.index("--output-schema") + 1]
        schema = json.loads(open(schema_path, encoding="utf-8").read())

        assert schema["type"] == "object"
        assert "assistant_summary" in schema["properties"]
        assert "memory_candidates" in schema["properties"]

        with open(output_path, "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "assistant_summary": "User prefers concise replies.",
                    "memory_candidates": [
                        "User prefers concise replies.",
                        "User works in Python.",
                    ],
                },
                handle,
            )
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr("mente.executors.codex.subprocess.run", fake_run)

    result = executor.execute(request)

    assert result.status == "success"
    assert result.summary == "User prefers concise replies."
    assert result.memory_candidates == [
        "User prefers concise replies.",
        "User works in Python.",
    ]


def test_codex_executor_execute_falls_back_when_structured_output_is_not_json(monkeypatch):
    executor = CodexExecutor(codex_binary="codex")
    request = ExecutionRequest(
        task_id="task_1",
        session_id="session_1",
        task_type="conversation",
        objective="Reply",
        user_request="Reply to the user",
        workspace=".",
    )

    def fake_run(command, capture_output, text, cwd, check, env):
        output_path = command[command.index("--output-last-message") + 1]
        with open(output_path, "w", encoding="utf-8") as handle:
            handle.write("plain text fallback")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr("mente.executors.codex.subprocess.run", fake_run)

    result = executor.execute(request)

    assert result.status == "success"
    assert result.summary == "plain text fallback"
    assert result.memory_candidates == []
