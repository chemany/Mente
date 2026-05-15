import logging
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

import gateway.run as gateway_run
from mente.integrations import bridge as mente_bridge
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


def test_resolve_gateway_runtime_continuity_lane_routes_simple_chat_to_director():
    lane = gateway_run._resolve_gateway_runtime_continuity_lane(
        message="你好，你是谁？",
        channel_prompt=None,
        recent_task_snapshot=None,
    )

    assert lane == "director"


def test_resolve_gateway_runtime_continuity_lane_routes_obvious_coding_turn_to_engineering(
    monkeypatch,
):
    monkeypatch.setattr(
        mente_bridge,
        "resolve_conversation_route",
        lambda **kwargs: type("Route", (), {"lane": "engineering"})(),
    )

    lane = gateway_run._resolve_gateway_runtime_continuity_lane(
        message="帮我修复 tests/gateway/test_session.py 的失败并跑 pytest",
        channel_prompt=None,
        recent_task_snapshot=None,
    )

    assert lane == "engineering"


def test_resolve_gateway_runtime_continuity_lane_prefers_active_lane_for_continue_turn():
    lane = gateway_run._resolve_gateway_runtime_continuity_lane(
        message="继续刚才的任务",
        channel_prompt=None,
        recent_task_snapshot={
            "user_request": "修复 tests/gateway/test_session.py 的失败并跑 pytest",
            "status": "running",
            "assistant_summary": "已定位到失败断言。",
            "metadata": {
                "lane": "engineering",
            },
        },
        active_lane="engineering",
    )

    assert lane == "director"


def test_resolve_gateway_runtime_continuity_lane_routes_status_follow_up_to_director():
    lane = gateway_run._resolve_gateway_runtime_continuity_lane(
        message="做到哪了？",
        channel_prompt=None,
        recent_task_snapshot={
            "user_request": "修复 tests/gateway/test_session.py 的失败并跑 pytest",
            "status": "running",
            "assistant_summary": "已定位到失败断言。",
            "follow_up_tasks": ["继续修复并跑测试"],
            "metadata": {
                "lane": "engineering",
            },
        },
        active_lane="engineering",
    )

    assert lane == "director"


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
        lane="director",
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


def test_resolve_gateway_runtime_continuity_plan_recent_artifact_delivery_starts_fresh():
    plan = gateway_run._resolve_gateway_runtime_continuity_plan(
        session_entry=MagicMock(session_id="sess-1"),
        history=_history(),
        continuity_payload={
            "runtime": "codex",
            "continuity_id": "thread-123",
            "status": "active",
        },
        recent_task_snapshot={
            "status": "needs_follow_up",
            "metadata": {
                "artifacts_out": [
                    "/home/jason/.mente/deep-research/report.md",
                    "/home/jason/.mente/deep-research/report.html",
                    "/home/jason/.mente/deep-research/report.docx",
                ]
            },
        },
        message="把刚才那三个报告上传到飞书云文档里",
        channel_prompt=None,
    )

    assert plan["execution_mode"] is ExecutionMode.SESSIONFUL
    assert plan["execution_session"] == ExecutionSession(mode=SessionMode.START)
    assert plan["fallback_history_fact"] is None
    assert plan["replay_history_in_memory_facts"] is False


def test_resolve_gateway_runtime_continuity_plan_status_follow_up_skips_history_replay():
    plan = gateway_run._resolve_gateway_runtime_continuity_plan(
        session_entry=MagicMock(session_id="sess-1"),
        history=_history(),
        continuity_payload=None,
        recent_task_snapshot={
            "user_request": "修复 tests/gateway/test_session.py 的失败并跑 pytest",
            "status": "running",
            "assistant_summary": "已定位到失败断言。",
            "follow_up_tasks": ["继续修复并跑测试"],
            "metadata": {
                "lane": "engineering",
            },
        },
        message="当前进度？",
        channel_prompt=None,
    )

    assert plan["execution_mode"] is ExecutionMode.SESSIONFUL
    assert plan["execution_session"] == ExecutionSession(mode=SessionMode.START)
    assert plan["fallback_history_fact"] is None
    assert plan["replay_history_in_memory_facts"] is False


def test_idle_expired_gateway_continuity_is_invalidated_and_restarts(monkeypatch):
    monkeypatch.setenv("MENTE_GATEWAY_CONTINUITY_IDLE_TTL_SECONDS", "3600")
    session_store = MagicMock()
    stale_updated_at = (datetime.now(timezone.utc) - timedelta(hours=5)).isoformat()

    payload = gateway_run._maybe_invalidate_gateway_runtime_continuity_when_idle_expired(
        session_store=session_store,
        session_id="sess-1",
        continuity_payload={
            "runtime": "codex",
            "continuity_id": "thread-123",
            "status": "active",
            "updated_at": stale_updated_at,
        },
    )

    session_store.invalidate_runtime_continuity.assert_called_once_with(
        "sess-1",
        lane="director",
        reason="idle_ttl_expired",
    )
    assert payload["status"] == "invalidated"
    assert payload["invalidation_reason"] == "idle_ttl_expired"

    plan = gateway_run._resolve_gateway_runtime_continuity_plan(
        session_entry=MagicMock(session_id="sess-1"),
        history=_history(),
        continuity_payload=payload,
    )

    assert plan["execution_mode"] is ExecutionMode.SESSIONFUL
    assert plan["execution_session"] == ExecutionSession(mode=SessionMode.START)
    assert plan["fallback_history_fact"].startswith("Conversation history (JSON):")
    assert plan["replay_history_in_memory_facts"] is False


def test_fresh_gateway_continuity_still_resumes(monkeypatch):
    monkeypatch.setenv("MENTE_GATEWAY_CONTINUITY_IDLE_TTL_SECONDS", "3600")
    session_store = MagicMock()
    fresh_updated_at = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()

    payload = gateway_run._maybe_invalidate_gateway_runtime_continuity_when_idle_expired(
        session_store=session_store,
        session_id="sess-1",
        continuity_payload={
            "runtime": "codex",
            "continuity_id": "thread-123",
            "status": "active",
            "updated_at": fresh_updated_at,
        },
    )

    session_store.invalidate_runtime_continuity.assert_not_called()
    assert payload["status"] == "active"

    plan = gateway_run._resolve_gateway_runtime_continuity_plan(
        session_entry=MagicMock(session_id="sess-1"),
        history=_history(),
        continuity_payload=payload,
    )

    assert plan["execution_session"] == ExecutionSession(
        mode=SessionMode.RESUME,
        continuity_id="thread-123",
    )


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


def test_resolve_gateway_runtime_continuity_plan_prefers_session_summary_over_history_replay():
    plan = gateway_run._resolve_gateway_runtime_continuity_plan(
        session_entry=MagicMock(session_id="sess-1"),
        history=_history(),
        continuity_payload={
            "runtime": "codex",
            "continuity_id": "thread-123",
            "status": "invalidated",
        },
        session_summary_available=True,
    )

    assert plan["execution_mode"] is ExecutionMode.SESSIONFUL
    assert plan["execution_session"] == ExecutionSession(mode=SessionMode.START)
    assert plan["fallback_history_fact"] is None
    assert plan["replay_history_in_memory_facts"] is False


def test_finalize_recent_task_snapshot_keeps_successful_artifact_outputs_for_follow_up():
    session_store = MagicMock()

    gateway_run._finalize_gateway_recent_task_snapshot(
        session_store=session_store,
        session_id="sess-1",
        message="深度研究藜芦醛市场，形成详细报告",
        lane="research",
        result={
            "failed": False,
            "lane": "research",
            "task_profile": "deep_research",
            "assistant_summary": "已生成 Markdown、HTML、DOCX 三份报告。",
            "artifacts_out": [
                "/home/jason/clawd/deep-research/report.md",
                "/home/jason/clawd/deep-research/report.html",
                "/home/jason/clawd/deep-research/report.docx",
            ],
            "follow_up_tasks": [],
        },
        previous_snapshot=None,
    )

    session_store.clear_recent_task_snapshot.assert_not_called()
    session_store.bind_recent_task_snapshot.assert_called_once()
    bind_kwargs = session_store.bind_recent_task_snapshot.call_args.kwargs
    assert bind_kwargs["lane"] == "research"
    assert bind_kwargs["status"] == "needs_follow_up"
    assert bind_kwargs["follow_up_tasks"] == []
    assert bind_kwargs["metadata"]["task_profile"] == "deep_research"
    assert bind_kwargs["metadata"]["artifacts_out"] == [
        "/home/jason/clawd/deep-research/report.md",
        "/home/jason/clawd/deep-research/report.html",
        "/home/jason/clawd/deep-research/report.docx",
    ]


def test_finalize_recent_task_snapshot_extracts_artifact_paths_from_summary_when_outputs_missing():
    session_store = MagicMock()

    gateway_run._finalize_gateway_recent_task_snapshot(
        session_store=session_store,
        session_id="sess-1",
        message="维拉帕米（Verapamil）的深度研究完成了么？",
        lane="research",
        result={
            "failed": False,
            "lane": "research",
            "task_profile": "deep_research",
            "assistant_summary": (
                "研究完成。\n"
                "Markdown: /home/jason/clawd/deep-research/verapamil/report.md\n"
                "HTML: /home/jason/clawd/deep-research/verapamil/report.html\n"
                "DOCX: /home/jason/clawd/deep-research/verapamil/report.docx"
            ),
            "artifacts_out": [],
            "follow_up_tasks": [],
        },
        previous_snapshot=None,
    )

    session_store.clear_recent_task_snapshot.assert_not_called()
    session_store.bind_recent_task_snapshot.assert_called_once()
    bind_kwargs = session_store.bind_recent_task_snapshot.call_args.kwargs
    assert bind_kwargs["status"] == "needs_follow_up"
    assert bind_kwargs["metadata"]["artifacts_out"] == [
        "/home/jason/clawd/deep-research/verapamil/report.md",
        "/home/jason/clawd/deep-research/verapamil/report.html",
        "/home/jason/clawd/deep-research/verapamil/report.docx",
    ]


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
        lane="engineering",
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
        lane="engineering",
        runtime="codex",
        continuity_id="thread-123",
        status="active",
        last_task_id="task-1",
        last_mode="start",
        last_fallback_reason=None,
    )
    session_store.invalidate_runtime_continuity.assert_not_called()


def test_record_gateway_runtime_continuity_result_invalidates_deep_research_thread_after_binding():
    session_store = MagicMock()

    gateway_run._record_gateway_runtime_continuity_result(
        session_store=session_store,
        session_id="sess-1",
        lane="research",
        task_id="task-1",
        previous_continuity_payload=None,
        execution_session_payload={
            "mode": "start",
            "continuity_id": "thread-123",
            "continuity_status": "started",
            "fallback_reason": None,
        },
        task_profile="deep_research",
    )

    session_store.bind_runtime_continuity.assert_called_once_with(
        "sess-1",
        lane="research",
        runtime="codex",
        continuity_id="thread-123",
        status="active",
        last_task_id="task-1",
        last_mode="start",
        last_fallback_reason=None,
    )
    session_store.invalidate_runtime_continuity.assert_called_once_with(
        "sess-1",
        lane="research",
        reason="deep_research_completed",
    )


def test_record_gateway_runtime_continuity_result_invalidates_previous_resume_on_fallback():
    session_store = MagicMock()

    gateway_run._record_gateway_runtime_continuity_result(
        session_store=session_store,
        session_id="sess-1",
        lane="engineering",
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
        lane="engineering",
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


def test_record_gateway_runtime_continuity_result_logs_diagnostics(caplog):
    session_store = MagicMock()

    with caplog.at_level(logging.INFO, logger="gateway.run"):
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
                "requested_mode": "start",
            },
        )

    assert any(
        "continuity_status=started" in record.message
        and "continuity_id=thread-123" in record.message
        and "session_id=sess-1" in record.message
        for record in caplog.records
    )
