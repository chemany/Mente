import json

import pytest

from mente.executors.codex import CodexExecutor
from mente.task_core.models import ExecutionRequest

from kernel.codex.runtime.protocol import (
    KernelExecutionPayload,
    KernelStructuredOutput,
    build_structured_output_schema,
    parse_structured_output,
)
from kernel.codex.session.protocol import KernelSessionMode, KernelSessionRequest


def _build_request() -> ExecutionRequest:
    return ExecutionRequest(
        task_id="task_1",
        session_id="session_1",
        task_type="conversation",
        objective="Reply",
        user_request="Reply to the user",
        workspace="/tmp/workspace",
        tool_policy={
            "policy_id": "gateway:conversation",
            "source": "gateway",
            "native_tools": ["shell"],
            "bridge_tools": ["mente_memory_query"],
            "session_capable": False,
        },
    )


def test_kernel_execution_payload_matches_current_adapter_shape():
    request = _build_request()
    payload = KernelExecutionPayload(
        prompt=CodexExecutor(codex_binary="codex").build_prompt(request),
        workspace=request.workspace,
        tool_policy=request.tool_policy,
    )

    assert payload.model_dump(mode="json") == {
        "prompt": CodexExecutor(codex_binary="codex").build_prompt(request),
        "workspace": "/tmp/workspace",
        "tool_policy": {
            "policy_id": "gateway:conversation",
            "source": "gateway",
            "native_tools": ["shell"],
            "bridge_tools": ["mente_memory_query"],
            "session_capable": False,
        },
    }


def test_kernel_session_protocol_distinguishes_stateless_from_future_session_mode():
    stateless = KernelSessionRequest(mode=KernelSessionMode.STATELESS)
    future_session = KernelSessionRequest(
        mode=KernelSessionMode.SESSION,
        session_id="kernel-session-123",
    )

    assert stateless.mode is KernelSessionMode.STATELESS
    assert stateless.session_id is None
    assert future_session.mode is KernelSessionMode.SESSION
    assert future_session.session_id == "kernel-session-123"


def test_structured_output_schema_matches_executor_contract():
    assert build_structured_output_schema() == {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "assistant_summary": {"type": "string"},
            "memory_candidates": {
                "type": "array",
                "items": {"type": "string"},
            },
        },
        "required": ["assistant_summary", "memory_candidates"],
    }


def test_parse_structured_output_accepts_valid_json_payload():
    parsed = parse_structured_output(
        json.dumps(
            {
                "assistant_summary": "User prefers concise replies.",
                "memory_candidates": ["User prefers concise replies."],
            }
        )
    )

    assert parsed == KernelStructuredOutput(
        assistant_summary="User prefers concise replies.",
        memory_candidates=["User prefers concise replies."],
    )


@pytest.mark.parametrize(
    "raw_output",
    [
        "",
        "not-json",
        "[]",
        json.dumps({"assistant_summary": 1, "memory_candidates": []}),
        json.dumps({"assistant_summary": "ok", "memory_candidates": "bad"}),
    ],
)
def test_parse_structured_output_rejects_malformed_payloads(raw_output: str):
    assert parse_structured_output(raw_output) is None
