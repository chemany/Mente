from __future__ import annotations

import json
from pathlib import Path

from kernel.codex.runtime.protocol import KernelExecutionPayload
from kernel.codex.runtime.result import KernelExecutionResult
from kernel.codex.runtime.transport import (
    KernelTransport,
    KernelTransportRequest,
    KernelTransportResponse,
)
from kernel.codex.runtime.runner import KernelRunner
from kernel.codex.runtime.transports.cli import CliKernelTransport
from mente.executors.runtime_config import RuntimeConfig

from kernel.codex.session.protocol import KernelSessionMode, KernelSessionRequest


class _RuntimeConfigStub:
    def __init__(self) -> None:
        self.runtime_home = Path("/tmp/private-codex-home")

    def to_codex_overrides(self) -> list[str]:
        return []


class _TransportStub:
    def execute(self, request: KernelTransportRequest) -> KernelTransportResponse:
        assert request.payload.prompt == "Inspect repository"
        assert request.session.mode is KernelSessionMode.STATELESS
        return KernelTransportResponse(
            command=["codex", "exec", "--ephemeral"],
            returncode=0,
            stdout="",
            stderr="",
            raw_output='{"assistant_summary":"done","memory_candidates":["remember this"]}',
        )


def test_kernel_execution_result_carries_kernel_owned_summary_memory_and_debug_fields():
    result = KernelExecutionResult(
        status="success",
        assistant_summary="done",
        memory_candidates=["remember this"],
        commands_run=["codex exec --ephemeral"],
        debug={"returncode": 0, "backend": "cli"},
        backend_failure=None,
    )

    assert result.model_dump(mode="json") == {
        "status": "success",
        "assistant_summary": "done",
        "memory_candidates": ["remember this"],
        "commands_run": ["codex exec --ephemeral"],
        "debug": {"returncode": 0, "backend": "cli"},
        "backend_failure": None,
    }


def test_kernel_transport_contract_stays_transport_neutral_and_separates_io_types():
    payload = KernelExecutionPayload(
        prompt="Inspect repository",
        workspace="/workspace/repo",
        tool_policy={"policy_id": "gateway:conversation"},
    )
    session = KernelSessionRequest(mode=KernelSessionMode.STATELESS)
    request = KernelTransportRequest(
        payload=payload,
        session=session,
        runtime_config=_RuntimeConfigStub(),
        sandbox="workspace-write",
        approval_policy="never",
        cwd="/workspace/repo",
        workdir="/tmp/mente-codex-workdir-123",
        output_last_message="/tmp/out.txt",
        output_schema="/tmp/schema.json",
        add_dirs=["/workspace/repo"],
    )

    transport = _TransportStub()
    response = transport.execute(request)

    assert isinstance(transport, KernelTransport)
    assert request.payload is payload
    assert request.session is session
    assert response.command == ["codex", "exec", "--ephemeral"]
    assert response.returncode == 0
    assert response.raw_output.startswith('{"assistant_summary"')
    assert not hasattr(request, "status")
    assert not isinstance(response, KernelExecutionResult)


def test_kernel_runner_uses_bridge_front_door_by_default(monkeypatch, tmp_path):
    runtime_workdir = tmp_path / "isolated-workdir"
    runtime_workdir.mkdir()
    captured: dict[str, object] = {}

    def fake_invoke_vendored_front_door(**kwargs):
        captured.update(kwargs)
        return type("_BridgeResult", (), {
            "command": ["/vendored/codex", "exec", "--ephemeral"],
            "returncode": 0,
            "stdout": "",
            "stderr": "",
            "raw_output": '{"assistant_summary":"vendored summary","memory_candidates":[]}',
            "backend_failure": None,
        })()

    monkeypatch.setattr(
        "kernel.codex.runtime.runner.prepare_isolated_workspace",
        lambda: runtime_workdir,
        raising=False,
    )
    monkeypatch.setattr(
        "kernel.codex.runtime.runner.invoke_vendored_front_door",
        fake_invoke_vendored_front_door,
        raising=False,
    )

    runner = KernelRunner()
    result = runner.run(
        payload=KernelExecutionPayload(
            prompt="Inspect repository",
            workspace=str(tmp_path),
            tool_policy=None,
        ),
        session=KernelSessionRequest(mode=KernelSessionMode.STATELESS),
        runtime_config=RuntimeConfig(runtime_home=tmp_path / "private-codex-home"),
    )

    assert captured["session"].mode is KernelSessionMode.STATELESS
    assert captured["workdir"] == str(runtime_workdir)
    assert result.commands_run == ["/vendored/codex exec --ephemeral"]
    assert result.assistant_summary == "vendored summary"


def test_kernel_runner_normalizes_stateless_transport_output(monkeypatch, tmp_path):
    runtime_workdir = tmp_path / "isolated-workdir"
    runtime_workdir.mkdir()
    captured: dict[str, object] = {}

    class _Transport:
        def execute(self, request: KernelTransportRequest) -> KernelTransportResponse:
            captured["request"] = request
            assert Path(request.output_schema).exists()
            return KernelTransportResponse(
                command=["codex", "exec", "--ephemeral"],
                returncode=0,
                stdout="",
                stderr="",
                raw_output=json.dumps(
                    {
                        "assistant_summary": "vendored summary",
                        "memory_candidates": ["remember this"],
                    }
                ),
            )

    monkeypatch.setattr(
        "kernel.codex.runtime.runner.prepare_isolated_workspace",
        lambda: runtime_workdir,
        raising=False,
    )

    runner = KernelRunner(transport=_Transport())
    result = runner.run(
        payload=KernelExecutionPayload(
            prompt="Inspect repository",
            workspace=str(tmp_path),
            tool_policy=None,
        ),
        session=KernelSessionRequest(mode=KernelSessionMode.STATELESS),
        runtime_config=RuntimeConfig(runtime_home=tmp_path / "private-codex-home"),
    )

    request = captured["request"]
    assert isinstance(request, KernelTransportRequest)
    assert request.workdir == str(runtime_workdir)
    assert request.add_dirs == [str(tmp_path.resolve())]
    assert result.status == "success"
    assert result.assistant_summary == "vendored summary"
    assert result.memory_candidates == ["remember this"]
    assert result.commands_run == ["codex exec --ephemeral"]
    assert result.debug["returncode"] == 0


def test_kernel_runner_rejects_session_mode_until_future_slice(tmp_path):
    class _Transport:
        def __init__(self) -> None:
            self.called = False

        def execute(self, request: KernelTransportRequest) -> KernelTransportResponse:
            self.called = True
            return KernelTransportResponse()

    transport = _Transport()
    runner = KernelRunner(transport=transport)

    result = runner.run(
        payload=KernelExecutionPayload(
            prompt="Inspect repository",
            workspace=str(tmp_path),
            tool_policy=None,
        ),
        session=KernelSessionRequest(
            mode=KernelSessionMode.SESSION,
            session_id="kernel-session-123",
        ),
        runtime_config=RuntimeConfig(runtime_home=tmp_path / "private-codex-home"),
    )

    assert transport.called is False
    assert result.status == "failed"
    assert result.backend_failure == "unsupported_session_mode"
    assert "session mode" in result.assistant_summary.lower()
