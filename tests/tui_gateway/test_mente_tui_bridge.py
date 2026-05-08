import logging
import types

from mente.executors import resolve_tool_exposure_policy
from mente.integrations.bridge import build_tui_task
from mente.task_core.models import ExecutionMode, ExecutionResult, ExecutionSession, SessionMode
from tui_gateway import server


def test_build_tui_task_sets_tui_source_and_continuity(tmp_path):
    fallback_history_fact = 'Conversation history (JSON):\n[{"role":"user","content":"before"}]'

    task = build_tui_task(
        user_message="latest question",
        conversation_history=[{"role": "user", "content": "before"}],
        session_id="tui-session-1",
        workspace=str(tmp_path),
        execution_mode=ExecutionMode.SESSIONFUL,
        execution_session=ExecutionSession(mode=SessionMode.START),
        fallback_history_fact=fallback_history_fact,
        replay_history_in_memory_facts=False,
    )

    assert task.task_type == "conversation"
    assert task.session_id == "tui-session-1"
    assert task.user_request == "latest question"
    assert task.workspace == str(tmp_path)
    assert task.execution_mode is ExecutionMode.SESSIONFUL
    assert task.execution_session == ExecutionSession(mode=SessionMode.START)
    assert task.metadata["source"] == "tui"
    assert task.metadata["fallback_history_fact"] == fallback_history_fact
    assert task.metadata["tool_policy"] == resolve_tool_exposure_policy(
        source="tui", task_type="conversation"
    ).as_metadata()
    assert not any(
        fact.startswith("Conversation history (JSON):") for fact in task.memory_facts
    )


def test_mente_tui_agent_routes_turns_through_bridge(monkeypatch):
    calls = []
    inner = types.SimpleNamespace(
        model="gpt-5.4",
        provider="openai",
        base_url="https://api.example.test/v1",
        api_key="sk-test",
        session_id="tui-session-1",
        run_conversation=lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("inner AIAgent.run_conversation should not be used")
        ),
    )

    def _fake_run_tui_task(**kwargs):
        calls.append(kwargs)
        return ExecutionResult(
            status="success",
            summary="via mente",
            metadata={
                "execution_session": {
                    "mode": "start",
                    "continuity_id": "thread-123",
                    "continuity_status": "started",
                    "fallback_reason": None,
                }
            },
        )

    monkeypatch.setenv("MENTE_SESSIONFUL_EXECUTION_ENABLED", "1")
    monkeypatch.setenv("MENTE_SESSIONFUL_EXECUTION_SOURCES", "api_server,gateway,tui")
    monkeypatch.setattr("mente.integrations.bridge.run_tui_task", _fake_run_tui_task)

    agent = server.MenteTuiAgent(inner, sid="sid-1", session_key="tui-session-1")
    history = [{"role": "assistant", "content": "before"}]

    result = agent.run_conversation(
        "latest question",
        conversation_history=list(history),
    )

    assert result["final_response"] == "via mente"
    assert result["messages"] == history + [
        {"role": "user", "content": "latest question"},
        {"role": "assistant", "content": "via mente"},
    ]
    assert calls[0]["execution_mode"] is ExecutionMode.SESSIONFUL
    assert calls[0]["execution_session"] == ExecutionSession(mode=SessionMode.START)
    assert calls[0]["replay_history_in_memory_facts"] is False
    assert calls[0]["fallback_history_fact"].startswith("Conversation history (JSON):")


def test_mente_tui_agent_defaults_to_continuity_when_feature_flag_enabled(monkeypatch):
    calls = []
    inner = types.SimpleNamespace(
        model="gpt-5.4",
        provider="openai",
        base_url="https://api.example.test/v1",
        api_key="sk-test",
        session_id="tui-session-1",
    )

    def _fake_run_tui_task(**kwargs):
        calls.append(kwargs)
        return ExecutionResult(
            status="success",
            summary="via mente",
            metadata={
                "execution_session": {
                    "mode": "start",
                    "continuity_id": "thread-123",
                    "continuity_status": "started",
                    "fallback_reason": None,
                }
            },
        )

    monkeypatch.setenv("MENTE_SESSIONFUL_EXECUTION_ENABLED", "1")
    monkeypatch.delenv("MENTE_SESSIONFUL_EXECUTION_SOURCES", raising=False)
    monkeypatch.setattr("mente.integrations.bridge.run_tui_task", _fake_run_tui_task)

    agent = server.MenteTuiAgent(inner, sid="sid-1", session_key="tui-session-1")

    agent.run_conversation("latest question", conversation_history=[])

    assert calls[0]["execution_mode"] is ExecutionMode.SESSIONFUL
    assert calls[0]["execution_session"] == ExecutionSession(mode=SessionMode.START)
    assert calls[0]["replay_history_in_memory_facts"] is False


def test_mente_tui_agent_resumes_previous_continuity(monkeypatch):
    calls = []
    inner = types.SimpleNamespace(
        model="gpt-5.4",
        provider="openai",
        base_url="https://api.example.test/v1",
        api_key="sk-test",
        session_id="tui-session-1",
    )

    def _fake_run_tui_task(**kwargs):
        calls.append(kwargs)
        continuity_id = "thread-123"
        return ExecutionResult(
            status="success",
            summary="ok",
            metadata={
                "execution_session": {
                    "mode": "resume" if len(calls) > 1 else "start",
                    "continuity_id": continuity_id,
                    "continuity_status": "resumed" if len(calls) > 1 else "started",
                    "fallback_reason": None,
                }
            },
        )

    monkeypatch.setenv("MENTE_SESSIONFUL_EXECUTION_ENABLED", "1")
    monkeypatch.setenv("MENTE_SESSIONFUL_EXECUTION_SOURCES", "api_server,gateway,tui")
    monkeypatch.setattr("mente.integrations.bridge.run_tui_task", _fake_run_tui_task)

    agent = server.MenteTuiAgent(inner, sid="sid-1", session_key="tui-session-1")

    agent.run_conversation("first", conversation_history=[])
    agent.run_conversation("second", conversation_history=[{"role": "assistant", "content": "ok"}])

    assert calls[1]["execution_mode"] is ExecutionMode.SESSIONFUL
    assert calls[1]["execution_session"] == ExecutionSession(
        mode=SessionMode.RESUME,
        continuity_id="thread-123",
    )
    assert calls[1]["replay_history_in_memory_facts"] is False
    assert calls[1]["fallback_history_fact"] is None


def test_mente_tui_agent_interrupt_cancels_active_turn():
    cancelled = []
    inner = types.SimpleNamespace(
        model="gpt-5.4",
        provider="openai",
        base_url="https://api.example.test/v1",
        api_key="sk-test",
        session_id="tui-session-1",
    )
    agent = server.MenteTuiAgent(inner, sid="sid-1", session_key="tui-session-1")
    agent._active_turn_controller = types.SimpleNamespace(cancel=lambda: cancelled.append(True))

    agent.interrupt()

    assert cancelled == [True]


def test_mente_tui_agent_logs_prompt_cache_and_continuity_diagnostics(monkeypatch, caplog):
    inner = types.SimpleNamespace(
        model="gpt-5.4",
        provider="openai",
        base_url="https://api.example.test/v1",
        api_key="sk-test",
        session_id="tui-session-1",
    )

    def _fake_run_tui_task(**kwargs):
        event_callback = kwargs.get("event_callback")
        assert callable(event_callback)
        event_callback(
            "executor.prompt_prepared",
            {
                "task_id": "task-1",
                "session_id": "tui-session-1",
                "prompt_char_count": 700,
                "memory_fact_count": 2,
                "memory_char_count": 96,
                "prompt_fingerprint": "fp-tui-123",
            },
        )
        event_callback(
            "kernel.codex.turn.completed",
            {
                "usage": {
                    "input_tokens": 1700,
                    "output_tokens": 20,
                    "cached_input_tokens": 1536,
                    "cache_write_tokens": 0,
                }
            },
        )
        return ExecutionResult(
            status="success",
            summary="via mente",
            metadata={
                "execution_session": {
                    "mode": "start",
                    "continuity_id": "thread-123",
                    "continuity_status": "started",
                    "fallback_reason": None,
                }
            },
        )

    monkeypatch.setenv("MENTE_SESSIONFUL_EXECUTION_ENABLED", "1")
    monkeypatch.setenv("MENTE_SESSIONFUL_EXECUTION_SOURCES", "api_server,gateway,tui")
    monkeypatch.setattr("mente.integrations.bridge.run_tui_task", _fake_run_tui_task)

    agent = server.MenteTuiAgent(inner, sid="sid-1", session_key="tui-session-1")

    with caplog.at_level(logging.INFO, logger="tui_gateway.server"):
        result = agent.run_conversation("latest question", conversation_history=[])

    assert result["final_response"] == "via mente"
    assert any(
        "prompt_fingerprint=fp-tui-123" in record.message
        and "memory_fact_count=2" in record.message
        for record in caplog.records
    )
    assert any(
        "cached_input_tokens=1536" in record.message
        and "session_id=tui-session-1" in record.message
        for record in caplog.records
    )
    assert any(
        "continuity_status=started" in record.message
        and "continuity_id=thread-123" in record.message
        for record in caplog.records
    )
