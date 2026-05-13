from types import SimpleNamespace

from gateway import run as gateway_run
from gateway.config import Platform
from gateway.platforms.base import MessageEvent, MessageType
from gateway.run import GatewayRunner, _GatewayBackgroundWorkerJob
from gateway.session import SessionSource, build_session_key
from mente.execution_events import persist_lane_progress_event
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


def _make_runner() -> GatewayRunner:
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
    return runner


def test_gateway_status_follow_up_prefers_persisted_worker_summary(monkeypatch, tmp_path):
    db_path = tmp_path / "tasks.db"
    monkeypatch.setattr(
        gateway_run,
        "SQLiteTaskRepository",
        lambda: SQLiteTaskRepository(db_path=db_path),
        raising=False,
    )
    runner = _make_runner()
    event = _make_event("当前进度？")
    session_key = build_session_key(event.source)

    runner._register_background_worker_job(
        session_key=session_key,
        session_id="sess-1",
        lane="research",
        job_id="job-1",
        task_id="task-1",
        summary="Background worker is still running.",
    )

    repo = SQLiteTaskRepository(db_path=db_path)
    persist_lane_progress_event(
        repo,
        event_type="kernel.codex.command.started",
        payload={"command": "/bin/bash -lc 'rg vendor docs/report.md'"},
        session_id="sess-1",
        lane="research",
        task_id="task-1",
        job_id="job-1",
    )
    persist_lane_progress_event(
        repo,
        event_type="kernel.codex.mcp_tool.started",
        payload={"tool": "mcp__mente__mente_memory_query"},
        session_id="sess-1",
        lane="research",
        task_id="task-1",
        job_id="job-1",
    )
    repo.close()

    response = runner._maybe_handle_background_worker_frontdesk_message(
        event,
        session_key=session_key,
        session_id="sess-1",
    )

    assert response is not None
    assert "research worker" in response
    assert "市场部正在调用工具：mente_memory_query" in response
    assert "Background worker is still running." not in response


def test_gateway_periodic_progress_prefers_persisted_summary_items(monkeypatch, tmp_path):
    db_path = tmp_path / "tasks.db"
    monkeypatch.setattr(
        gateway_run,
        "SQLiteTaskRepository",
        lambda: SQLiteTaskRepository(db_path=db_path),
        raising=False,
    )
    repo = SQLiteTaskRepository(db_path=db_path)
    persist_lane_progress_event(
        repo,
        event_type="kernel.codex.command.started",
        payload={"command": "/bin/bash -lc 'rg vendor docs/report.md'"},
        session_id="sess-1",
        lane="research",
        task_id="task-2",
        job_id="job-2",
    )
    persist_lane_progress_event(
        repo,
        event_type="kernel.codex.web_search.started",
        payload={"query": "vendor pricing benchmark"},
        session_id="sess-1",
        lane="research",
        task_id="task-2",
        job_id="job-2",
    )
    repo.close()

    job = _GatewayBackgroundWorkerJob(
        session_key="session-key",
        session_id="sess-1",
        lane="research",
        job_id="job-2",
        task_id="task-2",
        status="running",
        summary="live callback summary",
    )

    items = gateway_run._resolve_background_worker_phase_progress_items(
        session_id="sess-1",
        job=job,
        live_items=["stale live callback"],
    )

    assert items == [
        "市场部正在执行：Bash · rg vendor report.md",
        "市场部正在检索信息：vendor pricing benchmark",
    ]
