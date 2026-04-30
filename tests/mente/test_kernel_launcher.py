import subprocess
from pathlib import Path

from kernel.codex.runtime.launcher import (
    build_private_runtime_env,
    build_stateless_command,
)
from kernel.codex.runtime.protocol import KernelExecutionPayload
from kernel.codex.runtime.transport import KernelTransportRequest
from kernel.codex.runtime.transports.cli import CliKernelTransport
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


def test_cli_transport_executes_vendored_launcher_and_captures_raw_output(monkeypatch, tmp_path):
    runtime_config = RuntimeConfig(runtime_home=tmp_path / "private-codex-home")
    output_path = tmp_path / "out.txt"
    schema_path = tmp_path / "schema.json"
    captured: dict[str, object] = {}

    def fake_build_stateless_command(**kwargs):
        captured["launcher_kwargs"] = kwargs
        return ["codex", "exec", "--ephemeral", "Inspect repository"]

    def fake_build_private_runtime_env(codex_home):
        captured["env_home"] = codex_home
        return {"HOME": str(codex_home), "CODEX_HOME": str(codex_home)}

    def fake_run(command, capture_output, text, cwd, check, env):
        output_path.write_text(
            '{"assistant_summary":"vendored summary","memory_candidates":[]}',
            encoding="utf-8",
        )
        captured["command"] = command
        captured["cwd"] = cwd
        captured["env"] = env
        return subprocess.CompletedProcess(command, 0, stdout="transport stdout", stderr="")

    monkeypatch.setattr(
        "kernel.codex.runtime.transports.cli.build_stateless_command",
        fake_build_stateless_command,
        raising=False,
    )
    monkeypatch.setattr(
        "kernel.codex.runtime.transports.cli.build_private_runtime_env",
        fake_build_private_runtime_env,
        raising=False,
    )
    monkeypatch.setattr("kernel.codex.runtime.transports.cli.subprocess.run", fake_run)

    transport = CliKernelTransport(codex_binary="codex")
    response = transport.execute(
        KernelTransportRequest(
            payload=KernelExecutionPayload(
                prompt="Inspect repository",
                workspace=str(tmp_path),
                tool_policy=None,
            ),
            session=KernelSessionRequest(mode=KernelSessionMode.STATELESS),
            runtime_config=runtime_config,
            sandbox="workspace-write",
            approval_policy="never",
            cwd=str(tmp_path),
            workdir=str(tmp_path / "isolated-workdir"),
            output_last_message=str(output_path),
            output_schema=str(schema_path),
            add_dirs=[str(tmp_path)],
        )
    )

    assert captured["launcher_kwargs"]["payload"].prompt == "Inspect repository"
    assert captured["launcher_kwargs"]["workdir"] == str(tmp_path / "isolated-workdir")
    assert captured["env_home"] == runtime_config.runtime_home
    assert captured["cwd"] == str(tmp_path)
    assert response.command == ["codex", "exec", "--ephemeral", "Inspect repository"]
    assert response.returncode == 0
    assert response.stdout == "transport stdout"
    assert response.raw_output == '{"assistant_summary":"vendored summary","memory_candidates":[]}'
