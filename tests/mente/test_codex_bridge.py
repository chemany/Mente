from pathlib import Path

from kernel.codex.bridge.entrypoints import get_codex_handoff_surface


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_vendored_bridge_surface_exposes_real_snapshot_roots_and_cutover_front_door():
    surface = get_codex_handoff_surface()

    assert surface.upstream_root == REPO_ROOT / "kernel/codex/upstream"
    assert surface.bridge_root == REPO_ROOT / "kernel/codex/bridge"
    assert surface.patch_root == REPO_ROOT / "kernel/codex/patches"
    assert surface.rust_cli_entrypoint == REPO_ROOT / "kernel/codex/upstream/codex-rs/cli/src/main.rs"
    assert surface.rust_exec_entrypoint == REPO_ROOT / "kernel/codex/upstream/codex-rs/exec/src/main.rs"
    assert surface.adapter_seam == "CodexKernelAdapter"
    assert surface.cutover_complete is False
    assert surface.execution_path_switched is False
    assert surface.selected_front_door == "vendored_runtime_binary"
    assert surface.bootstrap_owner == "kernel.codex.bridge"
    assert surface.uses_public_codex_binary is False


def test_vendored_bridge_surface_exposes_release_runtime_locator_policy_without_sys_path_hacks():
    surface = get_codex_handoff_surface()

    assert surface.python_sdk_root == REPO_ROOT / "kernel/codex/upstream/sdk/python/src"
    assert surface.app_server_root == REPO_ROOT / "kernel/codex/upstream/sdk/python/src/codex_app_server"
    assert surface.runtime_locator_module == REPO_ROOT / "kernel/codex/release/runtime.py"
    assert "kernel/codex/release/artifacts/" in str(surface.runtime_binary_path)
    assert surface.runtime_locator_policy == "mente_release_freeze_manifest"
    assert surface.requires_sys_path_injection is False
    assert surface.uses_ambient_codex_discovery is False


def test_vendored_bridge_runtime_binary_path_comes_from_release_artifact_layout_gap():
    surface = get_codex_handoff_surface()

    assert "kernel/codex/release/artifacts/" in str(surface.runtime_binary_path)
    assert surface.runtime_binary_path.exists() is False

import subprocess

from kernel.codex.session.protocol import KernelSessionMode, KernelSessionRequest
from kernel.codex.runtime.protocol import KernelExecutionPayload
from mente.executors.runtime_config import RuntimeConfig
from kernel.codex.bridge.entrypoints import build_vendored_command, invoke_vendored_front_door


def test_bridge_builds_stateless_vendored_command_from_bridge_owned_front_door(monkeypatch, tmp_path):
    surface = get_codex_handoff_surface()
    fake_runtime = tmp_path / "runtime" / "codex"
    fake_runtime.parent.mkdir(parents=True)
    fake_runtime.write_text("#!/bin/sh\n", encoding="utf-8")
    fake_runtime.chmod(0o755)
    monkeypatch.setenv("MENTE_CODEX_RUNTIME_BIN", str(fake_runtime))
    command = build_vendored_command(
        payload=KernelExecutionPayload(
            prompt="Inspect repository",
            workspace=str(tmp_path),
            tool_policy=None,
        ),
        session=KernelSessionRequest(mode=KernelSessionMode.STATELESS),
        runtime_config=RuntimeConfig(runtime_home=tmp_path / "private-codex-home"),
        sandbox="workspace-write",
        approval_policy="never",
        output_last_message=str(tmp_path / "out.txt"),
        output_schema=str(tmp_path / "schema.json"),
        workdir=str(tmp_path / "isolated-workdir"),
        add_dirs=[str(tmp_path)],
    )

    assert command[:3] == [str(fake_runtime), "exec", "--ephemeral"]
    assert "--output-schema" in command
    assert command[-1] == "Inspect repository"


def test_bridge_uses_explicit_runtime_override_and_never_public_codex_path(monkeypatch, tmp_path):
    fake_runtime = tmp_path / "runtime" / "codex"
    fake_runtime.parent.mkdir(parents=True)
    fake_runtime.write_text("#!/bin/sh\n", encoding="utf-8")
    fake_runtime.chmod(0o755)
    monkeypatch.setenv("MENTE_CODEX_RUNTIME_BIN", str(fake_runtime))
    monkeypatch.setenv("PATH", str(tmp_path / "public-bin"))

    command = build_vendored_command(
        payload=KernelExecutionPayload(
            prompt="Inspect repository",
            workspace=str(tmp_path),
            tool_policy=None,
        ),
        session=KernelSessionRequest(mode=KernelSessionMode.STATELESS),
        runtime_config=RuntimeConfig(runtime_home=tmp_path / "private-codex-home"),
        sandbox="workspace-write",
        approval_policy="never",
        output_last_message=str(tmp_path / "out.txt"),
        output_schema=str(tmp_path / "schema.json"),
        workdir=str(tmp_path / "isolated-workdir"),
        add_dirs=[str(tmp_path)],
    )

    assert command[0] == str(fake_runtime)
    assert command[0] != "codex"


def test_bridge_fails_closed_when_runtime_not_bootstrapped_and_does_not_fallback_to_public_codex(
    monkeypatch, tmp_path
):
    public_bin = tmp_path / "public-bin"
    public_bin.mkdir()
    public_codex = public_bin / "codex"
    public_codex.write_text("#!/bin/sh\n", encoding="utf-8")
    public_codex.chmod(0o755)
    monkeypatch.delenv("MENTE_CODEX_RUNTIME_BIN", raising=False)
    monkeypatch.setenv("PATH", str(public_bin))

    result = invoke_vendored_front_door(
        payload=KernelExecutionPayload(
            prompt="Inspect repository",
            workspace=str(tmp_path),
            tool_policy=None,
        ),
        session=KernelSessionRequest(mode=KernelSessionMode.STATELESS),
        runtime_config=RuntimeConfig(runtime_home=tmp_path / "private-codex-home"),
        sandbox="workspace-write",
        approval_policy="never",
        cwd=str(tmp_path),
        workdir=str(tmp_path / "isolated-workdir"),
        output_last_message=str(tmp_path / "out.txt"),
        output_schema=str(tmp_path / "schema.json"),
        add_dirs=[str(tmp_path)],
        subprocess_run=lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not spawn")),
    )

    assert result.command == []
    assert result.returncode is None
    assert result.backend_failure is not None
    assert result.backend_failure.startswith("runtime_not_bootstrapped:")
    assert "public codex fallback is disabled" in result.backend_failure


def test_bridge_rejects_session_mode_without_spawning_and_keeps_bridge_metadata(tmp_path):
    result = invoke_vendored_front_door(
        payload=KernelExecutionPayload(
            prompt="Inspect repository",
            workspace=str(tmp_path),
            tool_policy=None,
        ),
        session=KernelSessionRequest(mode=KernelSessionMode.SESSION, session_id="session-1"),
        runtime_config=RuntimeConfig(runtime_home=tmp_path / "private-codex-home"),
        sandbox="workspace-write",
        approval_policy="never",
        cwd=str(tmp_path),
        workdir=str(tmp_path / "isolated-workdir"),
        output_last_message=str(tmp_path / "out.txt"),
        output_schema=str(tmp_path / "schema.json"),
        add_dirs=[str(tmp_path)],
        subprocess_run=lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not spawn")),
    )

    assert result.backend_failure == "unsupported_session_mode"
    assert result.returncode is None
    assert result.command == []
    assert result.front_door_mode == "vendored_runtime_binary"
    assert result.front_door_strategy == "bridge_selected"


def test_bridge_invokes_bridge_selected_front_door_and_normalizes_subprocess_result(monkeypatch, tmp_path):
    output_path = tmp_path / "out.txt"
    captured: dict[str, object] = {}
    fake_runtime = tmp_path / "runtime" / "codex"
    fake_runtime.parent.mkdir(parents=True)
    fake_runtime.write_text("#!/bin/sh\n", encoding="utf-8")
    fake_runtime.chmod(0o755)
    monkeypatch.setenv("MENTE_CODEX_RUNTIME_BIN", str(fake_runtime))

    def fake_run(command, capture_output, text, cwd, check, env):
        output_path.write_text(
            '{"assistant_summary":"vendored summary","memory_candidates":[]}',
            encoding="utf-8",
        )
        captured["command"] = command
        captured["cwd"] = cwd
        captured["env"] = env
        return subprocess.CompletedProcess(command, 0, stdout="bridge stdout", stderr="")

    result = invoke_vendored_front_door(
        payload=KernelExecutionPayload(
            prompt="Inspect repository",
            workspace=str(tmp_path),
            tool_policy=None,
        ),
        session=KernelSessionRequest(mode=KernelSessionMode.STATELESS),
        runtime_config=RuntimeConfig(runtime_home=tmp_path / "private-codex-home"),
        sandbox="workspace-write",
        approval_policy="never",
        cwd=str(tmp_path),
        workdir=str(tmp_path / "isolated-workdir"),
        output_last_message=str(output_path),
        output_schema=str(tmp_path / "schema.json"),
        add_dirs=[str(tmp_path)],
        subprocess_run=fake_run,
    )

    assert result.command == captured["command"]
    assert result.command[0] == str(fake_runtime)
    assert result.returncode == 0
    assert result.stdout == "bridge stdout"
    assert result.raw_output == '{"assistant_summary":"vendored summary","memory_candidates":[]}'
    assert result.front_door_mode == "vendored_runtime_binary"
    assert result.front_door_strategy == "bridge_selected"
