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


def test_kernel_runner_preserves_session_mode_when_transport_supports_it(tmp_path):
    class _Transport:
        def __init__(self) -> None:
            self.called = False

        def execute(self, request: KernelTransportRequest) -> KernelTransportResponse:
            self.called = True
            assert request.session.mode is KernelSessionMode.SESSION
            return KernelTransportResponse(
                command=["codex", "exec", "resume", "thread-123"],
                returncode=0,
                stdout='{"type":"thread.started","thread_id":"thread-123"}\n',
                stderr="",
                raw_output='{"assistant_summary":"done","memory_candidates":[]}',
            )

    transport = _Transport()
    runner = KernelRunner(transport=transport)

    result = runner.run(
        payload=KernelExecutionPayload(
            prompt="Inspect repository",
            workspace=str(tmp_path),
            tool_policy=None,
        ),
        session=KernelSessionRequest(mode=KernelSessionMode.SESSION),
        runtime_config=RuntimeConfig(runtime_home=tmp_path / "private-codex-home"),
    )

    assert transport.called is True
    assert result.status == "success"
    assert result.backend_failure is None
    assert result.assistant_summary == "done"
    assert result.debug["thread_id"] == "thread-123"


def test_kernel_runner_emits_runtime_events_for_stateless_execution(monkeypatch, tmp_path):
    runtime_workdir = tmp_path / "isolated-workdir"
    runtime_workdir.mkdir()
    events: list[tuple[str, dict[str, object]]] = []

    class _Transport:
        def execute(self, request: KernelTransportRequest) -> KernelTransportResponse:
            return KernelTransportResponse(
                command=["codex", "exec", "--ephemeral"],
                returncode=0,
                stdout="",
                stderr="",
                raw_output='{"assistant_summary":"vendored summary","memory_candidates":[]}',
            )

    monkeypatch.setattr(
        "kernel.codex.runtime.runner.prepare_isolated_workspace",
        lambda: runtime_workdir,
        raising=False,
    )

    runner = KernelRunner(
        transport=_Transport(),
        event_callback=lambda event_type, payload: events.append((event_type, payload)),
    )
    result = runner.run(
        payload=KernelExecutionPayload(
            prompt="Inspect repository",
            workspace=str(tmp_path),
            tool_policy=None,
        ),
        session=KernelSessionRequest(mode=KernelSessionMode.STATELESS),
        runtime_config=RuntimeConfig(runtime_home=tmp_path / "private-codex-home"),
    )

    assert result.status == "success"
    assert [event_type for event_type, _payload in events] == [
        "kernel.workspace_prepared",
        "kernel.transport_invoking",
        "kernel.transport_completed",
    ]
    assert events[0][1]["workdir"] == str(runtime_workdir)
    assert events[-1][1]["returncode"] == 0


def test_kernel_runner_forwards_codex_jsonl_events_during_bridge_execution(monkeypatch, tmp_path):
    runtime_workdir = tmp_path / "isolated-workdir"
    runtime_workdir.mkdir()
    events: list[tuple[str, dict[str, object]]] = []

    def fake_invoke_vendored_front_door(**kwargs):
        stdout_line_callback = kwargs["stdout_line_callback"]
        stdout_line_callback('{"type":"turn.started"}')
        stdout_line_callback(
            json.dumps(
                {
                    "type": "item.started",
                    "item": {
                        "id": "item_0",
                        "type": "command_execution",
                        "command": "node scripts/publisher/create-article.js",
                        "aggregated_output": "",
                        "exit_code": None,
                        "status": "in_progress",
                    },
                }
            )
        )
        stdout_line_callback(
            json.dumps(
                {
                    "type": "item.completed",
                    "item": {
                        "id": "item_0",
                        "type": "command_execution",
                        "command": "node scripts/publisher/create-article.js",
                        "aggregated_output": "ok",
                        "exit_code": 0,
                        "status": "completed",
                    },
                }
            )
        )
        stdout_line_callback(
            json.dumps(
                {
                    "type": "item.started",
                    "item": {
                        "id": "item_1",
                        "type": "mcp_tool_call",
                        "server": "mente",
                        "tool": "mente_wechat_publish_draft",
                        "arguments": {"article_path": "/tmp/article.md"},
                        "status": "in_progress",
                        "result": None,
                        "error": None,
                    },
                }
            )
        )
        stdout_line_callback(
            json.dumps(
                {
                    "type": "item.completed",
                    "item": {
                        "id": "item_1",
                        "type": "mcp_tool_call",
                        "server": "mente",
                        "tool": "mente_wechat_publish_draft",
                        "arguments": {"article_path": "/tmp/article.md"},
                        "status": "completed",
                        "result": {"content": [], "structured_content": {"ok": True}},
                        "error": None,
                    },
                }
            )
        )
        return type(
            "_BridgeResult",
            (),
            {
                "command": ["/vendored/codex", "exec", "--ephemeral", "--json"],
                "returncode": 0,
                "stdout": "",
                "stderr": "",
                "raw_output": '{"assistant_summary":"vendored summary","memory_candidates":[]}',
                "backend_failure": None,
            },
        )()

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

    runner = KernelRunner(
        event_callback=lambda event_type, payload: events.append((event_type, payload)),
    )
    result = runner.run(
        payload=KernelExecutionPayload(
            prompt="Inspect repository",
            workspace=str(tmp_path),
            tool_policy=None,
        ),
        session=KernelSessionRequest(mode=KernelSessionMode.STATELESS),
        runtime_config=RuntimeConfig(runtime_home=tmp_path / "private-codex-home"),
    )

    assert result.status == "success"
    assert [event_type for event_type, _payload in events] == [
        "kernel.workspace_prepared",
        "kernel.bridge_invoking",
        "kernel.codex.turn.started",
        "kernel.codex.command.started",
        "kernel.codex.command.completed",
        "kernel.codex.mcp_tool.started",
        "kernel.codex.mcp_tool.completed",
        "kernel.bridge_completed",
    ]
    assert events[3][1]["command"] == "node scripts/publisher/create-article.js"
    assert events[5][1]["tool"] == "mente_wechat_publish_draft"
