import threading
from pathlib import Path
from types import SimpleNamespace

from gateway import run as gateway_run
from gateway.config import GatewayConfig, Platform
from gateway.platforms.base import MessageEvent, MessageType
from gateway.session import SessionSource, SessionStore, build_session_key
from mente.execution_events import read_persisted_lane_job
from mente.integrations.bridge import build_gateway_task_bundle
from mente.task_core.models import (
    DispatchMode,
    ExecutionMode,
    Task,
    TaskRole,
    TaskStatus,
)
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


def _make_runner(tmp_path: Path, monkeypatch) -> tuple[gateway_run.GatewayRunner, Path]:
    db_path = tmp_path / "tasks.db"
    monkeypatch.setattr(
        gateway_run,
        "SQLiteTaskRepository",
        lambda: SQLiteTaskRepository(db_path=db_path),
        raising=False,
    )

    runner = object.__new__(gateway_run.GatewayRunner)
    runner._running_agents = {}
    runner._running_agents_ts = {}
    runner._background_worker_registry = {}
    runner._busy_ack_ts = {}
    runner._pending_messages = {}
    runner._queued_events = {}
    runner.config = SimpleNamespace()
    runner._draining = False

    session_store = SessionStore(
        sessions_dir=tmp_path / "sessions",
        config=GatewayConfig(),
    )
    adapter = SimpleNamespace(_pending_messages={})
    runner.adapters = {Platform.TELEGRAM: adapter}
    runner.session_store = session_store
    return runner, db_path


def _save_worker_task(db_path: Path, *, session_id: str, job_id: str, task_id: str) -> None:
    repo = SQLiteTaskRepository(db_path=db_path)
    repo.save(
        Task(
            task_id=task_id,
            session_id=session_id,
            task_type="conversation",
            objective="Run the delegated worker task.",
            user_request="研究供应商价格",
            status=TaskStatus.EXECUTING,
            role=TaskRole.WORKER,
            dispatch_mode=DispatchMode.DELEGATE_BACKGROUND,
            worker_lane="research",
            job_id=job_id,
            execution_mode=ExecutionMode.STATELESS,
            metadata={
                "source": "gateway",
                "lane": "research",
                "task_profile": "deep_research",
                "skill_refs": ["skills/research/web"],
            },
        )
    )
    repo.close()


def test_pause_this_research_marks_worker_paused_and_keeps_frontdesk_live(
    monkeypatch, tmp_path
):
    runner, db_path = _make_runner(tmp_path, monkeypatch)
    session_id = "sess-1"
    source = _make_source()
    session_key = build_session_key(source)
    cancel_event = threading.Event()

    runner._running_agents[session_key] = object()
    runner._register_background_worker_job(
        session_key=session_key,
        session_id=session_id,
        lane="research",
        job_id="job-research-1",
        task_id="task-research-1",
        status="running",
        summary="Collecting vendor data",
        metadata={"lane": "research", "task_profile": "deep_research"},
        cancel_event=cancel_event,
    )

    response = runner._maybe_handle_background_worker_frontdesk_message(
        _make_event("暂停这个研究"),
        session_key=session_key,
        session_id=session_id,
    )

    assert response is not None
    paused_job = runner._get_background_worker_job(session_key, lane="research")
    assert paused_job is not None
    assert paused_job.status == "paused"
    assert cancel_event.is_set() is False
    assert session_key in runner._running_agents

    repo = SQLiteTaskRepository(db_path=db_path)
    persisted = read_persisted_lane_job(
        repo,
        session_id=session_id,
        lane="research",
        job_id="job-research-1",
        task_id="task-research-1",
    )
    repo.close()

    assert persisted is not None
    assert persisted["latest_job_state"] == "paused"
    assert persisted["metadata"]["control_contract"]["action"] == "pause"


def test_cancel_last_task_hits_worker_cancel_event_and_persists_checkpoint(
    monkeypatch, tmp_path
):
    runner, db_path = _make_runner(tmp_path, monkeypatch)
    session_id = "sess-1"
    source = _make_source()
    session_key = build_session_key(source)
    cancel_event = threading.Event()

    runner._register_background_worker_job(
        session_key=session_key,
        session_id=session_id,
        lane="research",
        job_id="job-research-1",
        task_id="task-research-1",
        status="running",
        summary="Collecting vendor data",
        metadata={"lane": "research", "task_profile": "deep_research"},
        cancel_event=cancel_event,
    )

    response = runner._maybe_handle_background_worker_frontdesk_message(
        _make_event("取消刚才那个任务"),
        session_key=session_key,
        session_id=session_id,
    )

    assert response is not None
    assert cancel_event.is_set() is True

    cancelled_job = runner._get_background_worker_job(session_key, lane="research")
    assert cancelled_job is not None
    assert cancelled_job.status == "cancelled"

    repo = SQLiteTaskRepository(db_path=db_path)
    persisted = read_persisted_lane_job(
        repo,
        session_id=session_id,
        lane="research",
        job_id="job-research-1",
        task_id="task-research-1",
    )
    repo.close()

    assert persisted is not None
    assert persisted["latest_job_state"] == "cancelled"
    assert persisted["failure_reason"] == "interrupted_by_user"
    assert persisted["metadata"]["final_checkpoint"]["status"] == "cancelled"
    assert persisted["metadata"]["latest_event_type"] == "lane.cancelled"


def test_continue_soft_paused_worker_returns_to_running_without_claiming_hard_resume(
    monkeypatch, tmp_path
):
    runner, db_path = _make_runner(tmp_path, monkeypatch)
    session_id = "sess-1"
    source = _make_source()
    session_key = build_session_key(source)

    runner._running_agents[session_key] = object()
    runner._register_background_worker_job(
        session_key=session_key,
        session_id=session_id,
        lane="research",
        job_id="job-research-1",
        task_id="task-research-1",
        status="paused",
        summary="Paused while comparing vendors",
        metadata={
            "lane": "research",
            "task_profile": "deep_research",
            "control_contract": {
                "action": "pause",
                "mode": "soft_pause",
                "runtime_mutation_supported": False,
            },
        },
    )

    response = runner._maybe_handle_background_worker_frontdesk_message(
        _make_event("继续跑"),
        session_key=session_key,
        session_id=session_id,
    )

    assert response is not None

    resumed_job = runner._get_background_worker_job(session_key, lane="research")
    assert resumed_job is not None
    assert resumed_job.status == "running"

    repo = SQLiteTaskRepository(db_path=db_path)
    persisted = read_persisted_lane_job(
        repo,
        session_id=session_id,
        lane="research",
        job_id="job-research-1",
        task_id="task-research-1",
    )
    repo.close()

    assert persisted is not None
    assert persisted["latest_job_state"] == "running"
    assert persisted["metadata"]["control_contract"]["action"] == "resume"
    assert persisted["metadata"]["control_contract"]["mode"] == "soft_resume"


def test_reprioritize_revision_supersedes_worker_and_preserves_lineage(
    monkeypatch, tmp_path
):
    runner, db_path = _make_runner(tmp_path, monkeypatch)
    session_id = "sess-1"
    source = _make_source()
    session_key = build_session_key(source)
    cancel_event = threading.Event()
    revision = "改成先比较价格，再写结论"

    runner._running_agents[session_key] = object()
    runner.session_store.bind_recent_task_snapshot(
        session_id,
        lane="research",
        user_request="研究三家供应商并写结论",
        status="running",
        assistant_summary="正在整理供应商资料",
        follow_up_tasks=["补齐价格对比"],
        metadata={
            "lane": "research",
            "task_profile": "deep_research",
            "skill_refs": ["skills/research/web"],
        },
    )
    _save_worker_task(
        db_path,
        session_id=session_id,
        job_id="job-research-1",
        task_id="task-research-1",
    )
    runner._register_background_worker_job(
        session_key=session_key,
        session_id=session_id,
        lane="research",
        job_id="job-research-1",
        task_id="task-research-1",
        status="running",
        summary="Collecting vendor data",
        metadata={
            "lane": "research",
            "task_profile": "deep_research",
            "skill_refs": ["skills/research/web"],
        },
        cancel_event=cancel_event,
    )

    response = runner._maybe_handle_background_worker_frontdesk_message(
        _make_event(revision),
        session_key=session_key,
        session_id=session_id,
    )

    assert response is not None
    assert cancel_event.is_set() is True

    queued_job = runner._get_background_worker_job(session_key, lane="research")
    assert queued_job is not None
    assert queued_job.job_id != "job-research-1"
    assert queued_job.status == "queued"
    assert queued_job.metadata["supersedes"]["job_id"] == "job-research-1"
    assert queued_job.metadata["supersedes"]["task_id"] == "task-research-1"
    assert queued_job.metadata["user_revision"] == revision
    assert runner.adapters[Platform.TELEGRAM]._pending_messages[session_key].text == revision

    repo = SQLiteTaskRepository(db_path=db_path)
    old_task = repo.get("task-research-1")
    persisted = read_persisted_lane_job(
        repo,
        session_id=session_id,
        lane="research",
        job_id=queued_job.job_id,
        task_id=queued_job.task_id,
    )
    repo.close()

    assert old_task is not None
    assert old_task.metadata["superseded_by"]["job_id"] == queued_job.job_id
    assert old_task.metadata["superseded_by"]["task_id"] == queued_job.task_id
    assert persisted is not None
    assert persisted["latest_job_state"] == "queued"
    assert persisted["metadata"]["supersedes"]["job_id"] == "job-research-1"
    assert persisted["metadata"]["control_contract"]["mode"] == "supersede_worker"

    bundle = build_gateway_task_bundle(
        message=revision,
        context_prompt="session context",
        history=[],
        source=source,
        session_id=session_id,
        session_key=session_key,
        recent_task_snapshot=runner.session_store.get_recent_task_snapshot(
            session_id,
            lane="research",
        ),
        active_lane="research",
    )

    assert bundle.worker_task is not None
    assert bundle.coordinator_task.job_id == queued_job.job_id
    assert bundle.worker_task.task_id == queued_job.task_id
    assert bundle.worker_task.metadata["supersedes"]["job_id"] == "job-research-1"
    assert bundle.worker_task.metadata["supersedes"]["task_id"] == "task-research-1"


def test_same_lane_follow_up_appends_without_cancelling_worker(monkeypatch, tmp_path):
    runner, db_path = _make_runner(tmp_path, monkeypatch)
    session_id = "sess-1"
    source = _make_source()
    session_key = build_session_key(source)
    cancel_event = threading.Event()
    follow_up = "顺便把价格对比单独列一节"
    monkeypatch.setattr(
        "mente.integrations.bridge.resolve_dispatch_decision",
        lambda **_kwargs: SimpleNamespace(
            dispatch_mode=DispatchMode.DELEGATE_BACKGROUND,
            target_job_lane="research",
            worker_lane=None,
            lane="director",
            skill_refs=("research/deep-research-pro",),
            task_profile="deep_research",
            needs_clarification=False,
            reason="test:same_lane_append",
        ),
    )

    runner._running_agents[session_key] = object()
    runner.session_store.bind_recent_task_snapshot(
        session_id,
        lane="research",
        user_request="研究三家供应商并写结论",
        status="running",
        assistant_summary="正在整理供应商资料",
        follow_up_tasks=["补齐价格对比"],
        metadata={
            "lane": "research",
            "task_profile": "deep_research",
            "skill_refs": ["skills/research/web"],
        },
    )
    _save_worker_task(
        db_path,
        session_id=session_id,
        job_id="job-research-1",
        task_id="task-research-1",
    )
    runner._register_background_worker_job(
        session_key=session_key,
        session_id=session_id,
        lane="research",
        job_id="job-research-1",
        task_id="task-research-1",
        status="running",
        summary="Collecting vendor data",
        metadata={
            "lane": "research",
            "task_profile": "deep_research",
            "skill_refs": ["skills/research/web"],
        },
        cancel_event=cancel_event,
    )

    response = runner._maybe_handle_background_worker_frontdesk_message(
        _make_event(follow_up),
        session_key=session_key,
        session_id=session_id,
    )

    assert response is not None
    assert cancel_event.is_set() is False

    active_job = runner._get_background_worker_job(session_key, lane="research")
    assert active_job is not None
    assert active_job.job_id == "job-research-1"
    assert active_job.task_id == "task-research-1"
    assert active_job.status == "running"
    assert active_job.metadata["control_contract"]["mode"] == "append_worker"
    assert runner.adapters[Platform.TELEGRAM]._pending_messages[session_key].text == follow_up

    snapshot = runner.session_store.get_recent_task_snapshot(session_id, lane="research")
    pending = snapshot["metadata"]["pending_worker_control"]
    assert pending["mode"] == "append_worker"
    assert pending["user_revision"] == follow_up
    assert pending["previous_job_id"] == "job-research-1"
    assert pending["previous_task_id"] == "task-research-1"

    repo = SQLiteTaskRepository(db_path=db_path)
    task = repo.get("task-research-1")
    repo.close()

    assert task is not None
    assert task.metadata["control_contract"]["mode"] == "append_worker"
    assert follow_up in task.metadata["appended_user_revisions"]

    bundle = build_gateway_task_bundle(
        message=follow_up,
        context_prompt="session context",
        history=[],
        source=source,
        session_id=session_id,
        session_key=session_key,
        recent_task_snapshot=snapshot,
        active_lane="research",
    )

    assert bundle.worker_task is not None
    assert bundle.worker_task.metadata["control_contract"]["mode"] == "append_worker"
    assert bundle.worker_task.metadata["previous_job_id"] == "job-research-1"
    assert bundle.worker_task.metadata["previous_task_id"] == "task-research-1"
