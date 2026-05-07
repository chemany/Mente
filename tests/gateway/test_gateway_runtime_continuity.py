from unittest.mock import MagicMock

import pytest

import gateway.run as gateway_run
from mente.task_core.models import ExecutionMode, ExecutionSession, SessionMode


def _history():
    return [{"role": "user", "content": "before"}]


@pytest.fixture(autouse=True)
def _enable_gateway_continuity_by_default(monkeypatch):
    monkeypatch.setenv("MENTE_SESSIONFUL_EXECUTION_ENABLED", "1")
    monkeypatch.setenv("MENTE_GATEWAY_CONTINUITY_ENABLED", "1")


def test_resolve_gateway_runtime_continuity_plan_disabled_flag_stays_stateless(monkeypatch):
    monkeypatch.delenv("MENTE_SESSIONFUL_EXECUTION_ENABLED", raising=False)
    monkeypatch.delenv("MENTE_GATEWAY_CONTINUITY_ENABLED", raising=False)

    plan = gateway_run._resolve_gateway_runtime_continuity_plan(
        session_entry=MagicMock(session_id="sess-1"),
        history=_history(),
        continuity_payload=None,
    )

    assert plan["execution_mode"] is ExecutionMode.STATELESS
    assert plan["execution_session"] is None
    assert plan["fallback_history_fact"] is None
    assert plan["replay_history_in_memory_facts"] is True


def test_disabled_gateway_continuity_invalidates_active_codex_binding(monkeypatch):
    monkeypatch.delenv("MENTE_SESSIONFUL_EXECUTION_ENABLED", raising=False)
    monkeypatch.delenv("MENTE_GATEWAY_CONTINUITY_ENABLED", raising=False)
    session_store = MagicMock()

    payload = gateway_run._maybe_invalidate_gateway_runtime_continuity_when_disabled(
        session_store=session_store,
        session_id="sess-1",
        continuity_payload={
            "runtime": "codex",
            "continuity_id": "thread-123",
            "status": "active",
        },
    )

    session_store.invalidate_runtime_continuity.assert_called_once_with(
        "sess-1",
        reason="continuity_disabled",
    )
    assert payload["status"] == "invalidated"
    assert payload["invalidation_reason"] == "continuity_disabled"


def test_resolve_gateway_runtime_continuity_plan_without_continuity_replays_history_once():
    plan = gateway_run._resolve_gateway_runtime_continuity_plan(
        session_entry=MagicMock(session_id="sess-1"),
        history=_history(),
        continuity_payload=None,
    )

    assert plan["execution_mode"] is ExecutionMode.SESSIONFUL
    assert plan["execution_session"] == ExecutionSession(mode=SessionMode.START)
    assert plan["fallback_history_fact"].startswith("Conversation history (JSON):")
    assert plan["replay_history_in_memory_facts"] is False


def test_resolve_gateway_runtime_continuity_plan_enabled_flag_uses_sessionful_start(
    monkeypatch,
):
    monkeypatch.setenv("MENTE_SESSIONFUL_EXECUTION_ENABLED", "1")
    monkeypatch.setenv("MENTE_GATEWAY_CONTINUITY_ENABLED", "1")

    plan = gateway_run._resolve_gateway_runtime_continuity_plan(
        session_entry=MagicMock(session_id="sess-1"),
        history=_history(),
        continuity_payload=None,
    )

    assert plan["execution_mode"] is ExecutionMode.SESSIONFUL
    assert plan["execution_session"] == ExecutionSession(mode=SessionMode.START)
    assert plan["fallback_history_fact"].startswith("Conversation history (JSON):")
    assert plan["replay_history_in_memory_facts"] is False


def test_resolve_gateway_runtime_continuity_plan_with_active_continuity_uses_resume():
    plan = gateway_run._resolve_gateway_runtime_continuity_plan(
        session_entry=MagicMock(session_id="sess-1"),
        history=_history(),
        continuity_payload={
            "runtime": "codex",
            "continuity_id": "thread-123",
            "status": "active",
        },
    )

    assert plan["execution_mode"] is ExecutionMode.SESSIONFUL
    assert plan["execution_session"] == ExecutionSession(
        mode=SessionMode.RESUME,
        continuity_id="thread-123",
    )
    assert plan["fallback_history_fact"] is None
    assert plan["replay_history_in_memory_facts"] is False


def test_resolve_gateway_runtime_continuity_plan_with_invalidated_continuity_replays_history():
    plan = gateway_run._resolve_gateway_runtime_continuity_plan(
        session_entry=MagicMock(session_id="sess-1"),
        history=_history(),
        continuity_payload={
            "runtime": "codex",
            "continuity_id": "thread-123",
            "status": "invalidated",
        },
    )

    assert plan["execution_mode"] is ExecutionMode.SESSIONFUL
    assert plan["execution_session"] == ExecutionSession(mode=SessionMode.START)
    assert plan["fallback_history_fact"].startswith("Conversation history (JSON):")
    assert plan["replay_history_in_memory_facts"] is False


def test_resolve_gateway_runtime_continuity_plan_ignores_active_other_runtime():
    plan = gateway_run._resolve_gateway_runtime_continuity_plan(
        session_entry=MagicMock(session_id="sess-1"),
        history=_history(),
        continuity_payload={
            "runtime": "other-runtime",
            "continuity_id": "thread-123",
            "status": "active",
        },
    )

    assert plan["execution_mode"] is ExecutionMode.SESSIONFUL
    assert plan["execution_session"] == ExecutionSession(mode=SessionMode.START)
    assert plan["fallback_history_fact"].startswith("Conversation history (JSON):")
    assert plan["replay_history_in_memory_facts"] is False


def test_record_gateway_runtime_continuity_result_binds_active_continuity():
    session_store = MagicMock()

    gateway_run._record_gateway_runtime_continuity_result(
        session_store=session_store,
        session_id="sess-1",
        task_id="task-1",
        previous_continuity_payload=None,
        execution_session_payload={
            "mode": "start",
            "continuity_id": "thread-123",
            "continuity_status": "started",
            "fallback_reason": None,
        },
    )

    session_store.bind_runtime_continuity.assert_called_once_with(
        "sess-1",
        runtime="codex",
        continuity_id="thread-123",
        status="active",
        last_task_id="task-1",
        last_mode="start",
        last_fallback_reason=None,
    )
    session_store.invalidate_runtime_continuity.assert_not_called()


def test_record_gateway_runtime_continuity_result_invalidates_previous_resume_on_fallback():
    session_store = MagicMock()

    gateway_run._record_gateway_runtime_continuity_result(
        session_store=session_store,
        session_id="sess-1",
        task_id="task-1",
        previous_continuity_payload={
            "runtime": "codex",
            "continuity_id": "thread-stale",
            "status": "active",
        },
        execution_session_payload={
            "mode": "stateless",
            "continuity_id": None,
            "continuity_status": "fallback_stateless",
            "fallback_reason": "thread_not_found",
            "requested_mode": "resume",
        },
    )

    session_store.invalidate_runtime_continuity.assert_called_once_with(
        "sess-1",
        reason="thread_not_found",
    )
    session_store.bind_runtime_continuity.assert_not_called()


def test_record_gateway_runtime_continuity_result_does_not_invalidate_other_runtime():
    session_store = MagicMock()

    gateway_run._record_gateway_runtime_continuity_result(
        session_store=session_store,
        session_id="sess-1",
        task_id="task-1",
        previous_continuity_payload={
            "runtime": "other-runtime",
            "continuity_id": "thread-stale",
            "status": "active",
        },
        execution_session_payload={
            "mode": "stateless",
            "continuity_id": None,
            "continuity_status": "fallback_stateless",
            "fallback_reason": "thread_not_found",
            "requested_mode": "resume",
        },
    )

    session_store.invalidate_runtime_continuity.assert_not_called()
    session_store.bind_runtime_continuity.assert_not_called()


def test_record_gateway_runtime_continuity_result_leaves_missing_start_unbound():
    session_store = MagicMock()

    gateway_run._record_gateway_runtime_continuity_result(
        session_store=session_store,
        session_id="sess-1",
        task_id="task-1",
        previous_continuity_payload=None,
        execution_session_payload={
            "mode": "start",
            "continuity_id": None,
            "continuity_status": "missing_continuity_id",
            "fallback_reason": "missing_thread_id",
        },
    )

    session_store.bind_runtime_continuity.assert_not_called()
    session_store.invalidate_runtime_continuity.assert_not_called()
