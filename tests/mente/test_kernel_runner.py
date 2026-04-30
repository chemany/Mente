from __future__ import annotations

from pathlib import Path

from kernel.codex.runtime.protocol import KernelExecutionPayload
from kernel.codex.runtime.result import KernelExecutionResult
from kernel.codex.runtime.transport import (
    KernelTransport,
    KernelTransportRequest,
    KernelTransportResponse,
)
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
