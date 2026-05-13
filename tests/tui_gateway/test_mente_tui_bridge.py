import logging
import types
from pathlib import Path

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
    assert task.metadata["lane"] == "director"
    assert task.metadata["workflow_contract"]["lane"] == {
        "name": "director",
        "router": "deterministic_v1",
        "resumable": True,
    }
    assert task.metadata["fallback_history_fact"] == fallback_history_fact
    assert task.metadata["tool_policy"] == resolve_tool_exposure_policy(
        source="tui", task_type="conversation"
    ).as_metadata()
    assert not any(
        fact.startswith("Conversation history (JSON):") for fact in task.memory_facts
    )


def test_build_tui_task_narrows_publish_profile_for_explicit_wechat_request(tmp_path):
    task = build_tui_task(
        user_message="把这篇文章发到微信公众号草稿箱",
        conversation_history=[],
        session_id="tui-session-publish",
        workspace=str(tmp_path),
    )

    assert task.metadata["source"] == "tui"
    assert task.metadata["lane"] == "writing"
    assert task.metadata["task_profile"] == "content_publishing"
    assert task.metadata["tool_policy"]["bridge_tools"] == ["mente_wechat_publish_draft"]


def test_build_tui_task_routes_obvious_coding_request_to_engineering_lane(tmp_path):
    task = build_tui_task(
        user_message="修复这个 pytest 失败，并查看 app.py 的报错",
        conversation_history=[],
        session_id="tui-session-code",
        workspace=str(tmp_path),
    )

    assert task.metadata["source"] == "tui"
    assert task.metadata["lane"] == "engineering"
    assert task.metadata["workflow_contract"]["continuity"]["lane"] == "engineering"


def test_build_tui_task_defaults_lane_workspace_under_mente_home(monkeypatch, tmp_path):
    mente_home = tmp_path / ".mente"
    fallback_cwd = tmp_path / "fallback-cwd"
    mente_home.mkdir()
    fallback_cwd.mkdir()
    monkeypatch.setenv("MENTE_HOME", str(mente_home))
    monkeypatch.setenv("TERMINAL_CWD", str(fallback_cwd))

    task = build_tui_task(
        user_message="修复这个 pytest 失败，并查看 app.py 的报错",
        conversation_history=[],
        session_id="tui-session-code",
    )

    assert task.metadata["lane"] == "engineering"
    assert task.workspace == str(mente_home / "workspace-engineering")
    assert Path(task.workspace).is_dir()


def test_build_tui_task_injects_lane_handoff_capsule_for_status_follow_up(tmp_path):
    task = build_tui_task(
        user_message="做到哪了？",
        conversation_history=[],
        session_id="tui-session-status",
        workspace=str(tmp_path),
        recent_task_snapshot={
            "user_request": "修复这个 pytest 失败，并查看 app.py 的报错",
            "status": "running",
            "assistant_summary": "已定位到 app.py 的报错位置。",
            "follow_up_tasks": ["继续修复并跑测试"],
            "metadata": {
                "lane": "engineering",
                "artifacts_out": ["/tmp/pytest.log"],
            },
        },
        active_lane="engineering",
    )

    capsule_fact = next(
        fact for fact in task.memory_facts if fact.startswith("Active lane handoff capsule:")
    )
    assert task.metadata["lane"] == "director"
    assert "engineering" in capsule_fact
    assert "已定位到 app.py 的报错位置。" in capsule_fact
    assert "继续修复并跑测试" in capsule_fact
    assert "pytest.log" in capsule_fact
    assert not any(
        fact.startswith("Recent active task snapshot:")
        for fact in task.memory_facts
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
    assert agent._continuity_payloads["director"]["continuity_id"] == "thread-123"
    assert agent._continuity_payloads["director"]["lane"] == "director"


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

    agent.run_conversation("修复这个 pytest 失败", conversation_history=[])
    agent.run_conversation("继续修这个 pytest 失败", conversation_history=[{"role": "assistant", "content": "ok"}])

    assert calls[1]["execution_mode"] is ExecutionMode.SESSIONFUL
    assert calls[1]["execution_session"] == ExecutionSession(
        mode=SessionMode.RESUME,
        continuity_id="thread-123",
    )
    assert calls[1]["replay_history_in_memory_facts"] is False
    assert calls[1]["fallback_history_fact"] is None
    assert set(agent._continuity_payloads) == {"engineering"}


def test_mente_tui_agent_reuses_active_engineering_lane_for_generic_continue_turn(monkeypatch):
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

    agent.run_conversation("修复这个 pytest 失败", conversation_history=[])
    agent.run_conversation("继续刚才的任务", conversation_history=[{"role": "assistant", "content": "ok"}])

    assert calls[1]["execution_mode"] is ExecutionMode.SESSIONFUL
    assert calls[1]["execution_session"] == ExecutionSession(
        mode=SessionMode.RESUME,
        continuity_id="thread-123",
    )
    assert set(agent._continuity_payloads) == {"engineering"}


def test_mente_tui_agent_uses_director_status_follow_up_without_losing_engineering_continuity(monkeypatch):
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
        prompt = kwargs["user_message"]
        if "pytest" in prompt or "修复" in prompt:
            continuity_id = "thread-engineering"
            metadata = {"lane": "engineering"}
            follow_up_tasks = ["继续修复并跑测试"]
            summary = "已定位到失败断言。"
        else:
            continuity_id = "thread-director"
            metadata = {"lane": "director"}
            follow_up_tasks = []
            summary = "当前正在修复 pytest 失败，已定位到失败断言。"
        return ExecutionResult(
            status="success",
            summary=summary,
            follow_up_tasks=follow_up_tasks,
            metadata={
                **metadata,
                "execution_session": {
                    "mode": "resume"
                    if kwargs.get("execution_session")
                    == ExecutionSession(mode=SessionMode.RESUME, continuity_id=continuity_id)
                    else "start",
                    "continuity_id": continuity_id,
                    "continuity_status": "resumed"
                    if kwargs.get("execution_session")
                    == ExecutionSession(mode=SessionMode.RESUME, continuity_id=continuity_id)
                    else "started",
                    "fallback_reason": None,
                },
            },
        )

    monkeypatch.setenv("MENTE_SESSIONFUL_EXECUTION_ENABLED", "1")
    monkeypatch.setenv("MENTE_SESSIONFUL_EXECUTION_SOURCES", "api_server,gateway,tui")
    monkeypatch.setattr("mente.integrations.bridge.run_tui_task", _fake_run_tui_task)

    agent = server.MenteTuiAgent(inner, sid="sid-1", session_key="tui-session-1")

    agent.run_conversation("修复这个 pytest 失败", conversation_history=[])
    agent.run_conversation("做到哪了？", conversation_history=[{"role": "assistant", "content": "ok"}])
    agent.run_conversation("继续刚才的任务", conversation_history=[{"role": "assistant", "content": "ok"}])

    assert calls[1]["execution_session"] == ExecutionSession(mode=SessionMode.START)
    assert calls[1]["fallback_history_fact"] is None
    assert calls[1]["replay_history_in_memory_facts"] is False
    assert calls[1]["recent_task_snapshot"]["assistant_summary"] == "已定位到失败断言。"
    assert calls[2]["execution_session"] == ExecutionSession(
        mode=SessionMode.RESUME,
        continuity_id="thread-engineering",
    )
    assert set(agent._continuity_payloads) == {"director", "engineering"}


def test_mente_tui_agent_keeps_director_and_engineering_continuity_separate(monkeypatch):
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
        prompt = kwargs["user_message"]
        if "pytest" in prompt or "修复" in prompt:
            continuity_id = "thread-engineering"
        else:
            continuity_id = "thread-director"
        return ExecutionResult(
            status="success",
            summary="ok",
            metadata={
                "execution_session": {
                    "mode": "resume"
                    if kwargs.get("execution_session") == ExecutionSession(
                        mode=SessionMode.RESUME,
                        continuity_id=continuity_id,
                    )
                    else "start",
                    "continuity_id": continuity_id,
                    "continuity_status": "resumed"
                    if kwargs.get("execution_session") == ExecutionSession(
                        mode=SessionMode.RESUME,
                        continuity_id=continuity_id,
                    )
                    else "started",
                    "fallback_reason": None,
                }
            },
        )

    monkeypatch.setenv("MENTE_SESSIONFUL_EXECUTION_ENABLED", "1")
    monkeypatch.setenv("MENTE_SESSIONFUL_EXECUTION_SOURCES", "api_server,gateway,tui")
    monkeypatch.setattr("mente.integrations.bridge.run_tui_task", _fake_run_tui_task)

    agent = server.MenteTuiAgent(inner, sid="sid-1", session_key="tui-session-1")

    agent.run_conversation("修复这个 pytest 失败", conversation_history=[])
    agent.run_conversation("你好，你是谁？", conversation_history=[{"role": "assistant", "content": "ok"}])
    agent.run_conversation("继续修复 pytest 失败", conversation_history=[{"role": "assistant", "content": "ok"}])

    assert calls[0]["execution_session"] == ExecutionSession(mode=SessionMode.START)
    assert calls[1]["execution_session"] == ExecutionSession(mode=SessionMode.START)
    assert calls[2]["execution_session"] == ExecutionSession(
        mode=SessionMode.RESUME,
        continuity_id="thread-engineering",
    )
    assert set(agent._continuity_payloads) == {"director", "engineering"}


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


def test_mente_tui_agent_emits_structured_lane_progress_events(monkeypatch):
    emitted = []
    inner = types.SimpleNamespace(
        model="gpt-5.4",
        provider="openai",
        base_url="https://api.example.test/v1",
        api_key="sk-test",
        session_id="tui-session-1",
    )

    def _fake_emit(event_type, sid, payload=None):
        emitted.append((event_type, sid, payload or {}))

    def _fake_run_tui_task(**kwargs):
        event_callback = kwargs.get("event_callback")
        assert callable(event_callback)
        event_callback(
            "kernel.codex.command.started",
            {"command": '/bin/bash -lc \'sed -n "1,40p" README.md\''},
        )
        return ExecutionResult(
            status="success",
            summary="done",
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
    monkeypatch.setattr(server, "_emit", _fake_emit)

    agent = server.MenteTuiAgent(inner, sid="sid-1", session_key="tui-session-1")

    result = agent.run_conversation("修复这个 pytest 失败", conversation_history=[])

    assert result["final_response"] == "done"
    assert any(
        event_type == "lane.progress"
        and payload.get("lane") == "engineering"
        and payload.get("detail") == "Bash · sed README.md"
        for event_type, _sid, payload in emitted
    )
    assert any(
        event_type == "thinking.delta"
        and "工程部正在执行：Bash · sed README.md" in str(payload.get("text") or "")
        for event_type, _sid, payload in emitted
    )
    assert any(
        event_type == "lane.completed"
        and payload.get("lane") == "engineering"
        and payload.get("status") == "completed"
        for event_type, _sid, payload in emitted
    )
