from types import SimpleNamespace

from gateway import run as gateway_run
from gateway.config import Platform
from gateway.platforms.base import MessageEvent, MessageType
from gateway.run import GatewayRunner, _GatewayBackgroundWorkerJob
from gateway.session import SessionSource, build_session_key
from mente.execution_events import persist_lane_terminal_event, persist_session_job_state
from mente.task_core.models import ExecutionResult
from mente.task_core.repository import SQLiteTaskRepository


def _make_source(chat_id: str = "chat-1") -> SessionSource:
    return SessionSource(
        platform=Platform.TELEGRAM,
        chat_id=chat_id,
        chat_type="dm",
        user_id="user-1",
        user_name="tester",
    )


def _make_event(text: str, chat_id: str = "chat-1") -> MessageEvent:
    return MessageEvent(
        text=text,
        message_type=MessageType.TEXT,
        source=_make_source(chat_id),
        message_id="msg-1",
    )


def _make_runner(monkeypatch, tmp_path) -> tuple[GatewayRunner, str, str]:
    db_path = tmp_path / "tasks.db"
    monkeypatch.setattr(
        gateway_run,
        "SQLiteTaskRepository",
        lambda: SQLiteTaskRepository(db_path=db_path),
        raising=False,
    )
    runner = object.__new__(GatewayRunner)
    runner._running_agents = {}
    runner._running_agents_ts = {}
    runner._background_worker_registry = {}
    runner._busy_ack_ts = {}
    runner._pending_messages = {}
    runner._queued_events = {}
    runner.adapters = {}
    runner.session_store = None
    runner.config = SimpleNamespace()
    runner._draining = False
    return runner, "sess-1", str(db_path)


def test_complex_delegated_request_ack_includes_lane_job_id_and_next_step():
    reply = gateway_run._render_background_worker_coordinator_reply(  # type: ignore[attr-defined]
        {
            "lane": "research",
            "job_id": "job-research-42",
            "status": "running",
            "summary": "市场部正在收集竞品资料",
            "metadata": {
                "task_profile": "deep_research",
                "reply_template": "accepted",
            },
        },
        reply_kind="accepted",
    )

    assert "research" in reply.lower()
    assert "job-research-42" in reply
    assert "正在" in reply
    assert "结果" not in reply


def test_status_follow_up_uses_persisted_progress_instead_of_live_placeholder(
    monkeypatch, tmp_path
):
    runner, session_id, _db_path = _make_runner(monkeypatch, tmp_path)
    event = _make_event("现在进度？")
    session_key = build_session_key(event.source)

    runner._register_background_worker_job(
        session_key=session_key,
        session_id=session_id,
        lane="research",
        job_id="job-1",
        task_id="task-1",
        status="running",
        summary="Background worker is still running.",
    )

    repo = gateway_run.SQLiteTaskRepository()
    persist_session_job_state(
        repo,
        session_id=session_id,
        lane="research",
        job_id="job-1",
        task_id="task-1",
        status="running",
        summary="当前在检索竞品资料，已整理两家厂商定价口径。",
        metadata={
            "job_state": "running",
            "summary_items": [
                "市场部正在检索竞品资料：厂商定价口径",
                "市场部正在整理结论：两家厂商差异",
            ],
        },
    )
    repo.close()

    reply = runner._maybe_handle_background_worker_frontdesk_message(
        event,
        session_key=session_key,
        session_id=session_id,
    )

    assert reply is not None
    assert "竞品资料" in reply
    assert "Background worker is still running." not in reply


def test_blocked_job_reply_includes_blocker_and_next_action(monkeypatch, tmp_path):
    runner, session_id, _db_path = _make_runner(monkeypatch, tmp_path)
    event = _make_event("现在卡在哪？")
    session_key = build_session_key(event.source)

    runner._register_background_worker_job(
        session_key=session_key,
        session_id=session_id,
        lane="research",
        job_id="job-2",
        task_id="task-2",
        status="blocked",
        summary="等待外部依赖",
    )

    repo = gateway_run.SQLiteTaskRepository()
    persist_session_job_state(
        repo,
        session_id=session_id,
        lane="research",
        job_id="job-2",
        task_id="task-2",
        status="blocked",
        summary="已暂停在资料抓取阶段。",
        metadata={
            "job_state": "blocked",
            "blocked_reason": "API key 缺失",
            "summary_items": ["市场部正在检索竞品资料：需要付费接口"],
        },
    )
    repo.close()

    reply = runner._maybe_handle_background_worker_frontdesk_message(
        event,
        session_key=session_key,
        session_id=session_id,
    )

    assert reply is not None
    assert "API key 缺失" in reply
    assert "建议" in reply or "是否" in reply


def test_completed_job_reply_uses_persisted_summary_and_artifacts_without_live_context(
    monkeypatch, tmp_path
):
    runner, session_id, _db_path = _make_runner(monkeypatch, tmp_path)
    event = _make_event("结果呢？")
    session_key = build_session_key(event.source)

    runner._register_background_worker_job(
        session_key=session_key,
        session_id=session_id,
        lane="research",
        job_id="job-3",
        task_id="task-3",
        status="completed",
        summary="live placeholder",
    )

    repo = gateway_run.SQLiteTaskRepository()
    persist_lane_terminal_event(
        repo,
        result=ExecutionResult(
            status="success",
            summary="研究已完成，结论是 A 厂商价格最低，B 厂商交付最快。",
            artifacts_out=[
                "/tmp/report.md",
                "/tmp/report.html",
            ],
        ),
        session_id=session_id,
        lane="research",
        task_id="task-3",
        job_id="job-3",
        metadata={"job_state": "completed"},
    )
    repo.close()

    reply = runner._maybe_handle_background_worker_frontdesk_message(
        event,
        session_key=session_key,
        session_id=session_id,
    )

    assert reply is not None
    assert "研究已完成" in reply
    assert "A 厂商价格最低" in reply
    assert "report.md" in reply


def test_reply_renderer_stays_deterministic_first_when_state_is_sufficient():
    calls: list[str] = []
    job = _GatewayBackgroundWorkerJob(
        session_key="session-key",
        session_id="sess-1",
        lane="research",
        job_id="job-4",
        task_id="task-4",
        status="completed",
        summary="研究已完成，已输出结论。",
        metadata={
            "job_state": "completed",
            "summary_items": ["市场部已完成：供应商对比结论"],
            "final_checkpoint": {
                "status": "completed",
                "headline": "任务已完成",
                "detail": "研究已完成，已输出结论。",
            },
            "latest_event_payload": {
                "artifacts": ["/tmp/final.md"],
            },
        },
    )

    reply = gateway_run._render_background_worker_coordinator_reply(  # type: ignore[attr-defined]
        {
            "lane": job.lane,
            "job_id": job.job_id,
            "task_id": job.task_id,
            "status": job.status,
            "summary": job.summary,
            "metadata": dict(job.metadata),
            "summary_items": list(job.metadata["summary_items"]),
        },
        reply_kind="completed",
        fallback_renderer=lambda *_args, **_kwargs: calls.append("fallback") or "fallback",
    )

    assert "final.md" in reply
    assert calls == []


def test_completed_job_reply_strips_future_tense_worker_promise():
    reply = gateway_run._render_background_worker_coordinator_reply(  # type: ignore[attr-defined]
        {
            "lane": "research",
            "job_id": "job-5",
            "status": "completed",
            "summary": (
                "内容已经从空模板扩展到8199字符，但还没到万字级别。"
                "我继续做更深度的扩写，增加更多细节和子章节。"
            ),
            "metadata": {
                "job_state": "completed",
            },
        },
        reply_kind="completed",
    )

    assert "8199字符" in reply
    assert "我继续做更深度的扩写" not in reply
    assert "当前没有继续执行中的后台动作" in reply
