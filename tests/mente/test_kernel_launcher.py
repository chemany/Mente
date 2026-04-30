from pathlib import Path

from kernel.codex.runtime.launcher import (
    build_private_runtime_env,
    build_stateless_command,
)
from kernel.codex.runtime.protocol import KernelExecutionPayload
from kernel.codex.session.protocol import KernelSessionMode, KernelSessionRequest
from kernel.codex.sandbox.workspace import prepare_isolated_workspace
from mente.executors.runtime_config import RuntimeConfig


def test_build_stateless_command_shapes_codex_exec_for_private_runtime():
    payload = KernelExecutionPayload(
        prompt="Inspect repository",
        workspace="/workspace/repo",
        tool_policy=None,
    )
    runtime_config = RuntimeConfig(
        runtime_home=Path("/private/codex-home"),
        codex_config={"model": "gpt-5.5"},
    )

    command = build_stateless_command(
        codex_binary="codex",
        payload=payload,
        session=KernelSessionRequest(mode=KernelSessionMode.STATELESS),
        sandbox="workspace-write",
        approval_policy="never",
        runtime_config=runtime_config,
        output_last_message="/tmp/out.txt",
        output_schema="/tmp/schema.json",
        workdir="/tmp/mente-codex-workdir-123",
        add_dirs=["/workspace/repo"],
    )

    assert command[:3] == ["codex", "exec", "--ephemeral"]
    assert "--ignore-user-config" in command
    assert "--ignore-rules" in command
    assert "--sandbox" in command
    assert "--full-auto" in command
    assert command[command.index("--cd") + 1] == "/tmp/mente-codex-workdir-123"
    assert command[command.index("--add-dir") + 1] == "/workspace/repo"
    assert command[command.index("--output-last-message") + 1] == "/tmp/out.txt"
    assert command[command.index("--output-schema") + 1] == "/tmp/schema.json"
    assert command[-1] == "Inspect repository"


def test_build_private_runtime_env_sets_private_home_and_preserves_safe_vars(monkeypatch):
    monkeypatch.setenv("PATH", "/usr/local/bin")
    monkeypatch.setenv("LANG", "C.UTF-8")
    monkeypatch.setenv("CODEX_HOME", "/shared/public-codex-home")

    env = build_private_runtime_env(Path("/private/codex-home"))

    assert env["PATH"] == "/usr/local/bin"
    assert env["LANG"] == "C.UTF-8"
    assert env["HOME"] == "/private/codex-home"
    assert env["CODEX_HOME"] == "/private/codex-home"


def test_prepare_isolated_workspace_creates_private_workdir(tmp_path):
    workdir = prepare_isolated_workspace()

    try:
        assert workdir.is_dir()
        assert workdir.resolve() == workdir
        assert workdir != tmp_path
        assert workdir.name.startswith("mente-codex-workdir-")
    finally:
        workdir.rmdir()
