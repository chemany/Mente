from mente.execution_events import (
    persist_lane_progress_event,
    persist_lane_terminal_event,
    read_persisted_lane_job,
)
from mente.task_core.models import ExecutionResult
from mente.task_core.repository import SQLiteTaskRepository


def test_every_normalized_lane_event_appends_to_task_event_log_and_updates_summary(tmp_path):
    repo = SQLiteTaskRepository(db_path=tmp_path / "state.db")

    persist_lane_progress_event(
        repo,
        event_type="kernel.codex.command.started",
        payload={"command": "/bin/bash -lc 'rg vendor docs/report.md'"},
        session_id="session-1",
        lane="research",
        task_id="task-1",
        job_id="job-1",
    )
    persist_lane_progress_event(
        repo,
        event_type="kernel.codex.mcp_tool.started",
        payload={"tool": "mcp__mente__mente_memory_query"},
        session_id="session-1",
        lane="research",
        task_id="task-1",
        job_id="job-1",
    )
    persist_lane_progress_event(
        repo,
        event_type="kernel.codex.mcp_tool.completed",
        payload={"tool": "mcp__mente__mente_memory_query", "error": "timeout"},
        session_id="session-1",
        lane="research",
        task_id="task-1",
        job_id="job-1",
    )

    events = repo.list_task_events("task-1")
    assert [event["event_type"] for event in events] == [
        "lane.blocked",
        "lane.progress",
        "lane.progress",
    ]

    snapshot = read_persisted_lane_job(
        repo,
        session_id="session-1",
        lane="research",
        job_id="job-1",
        task_id="task-1",
    )

    assert snapshot is not None
    assert snapshot["latest_job_state"] == "blocked"
    assert snapshot["blocked_reason"] == "timeout"
    assert len(snapshot["summary_items"]) == 3
    assert snapshot["summary_items"][-1] == "市场部工具执行失败：mente_memory_query"
    assert "市场部正在执行：Bash · rg vendor report.md" in snapshot["summary"]


def test_completed_job_writes_final_checkpoint_summary_readable_by_coordinator(tmp_path):
    repo = SQLiteTaskRepository(db_path=tmp_path / "state.db")

    persist_lane_progress_event(
        repo,
        event_type="kernel.codex.web_search.started",
        payload={"query": "vendor pricing benchmarks"},
        session_id="session-1",
        lane="research",
        task_id="task-2",
        job_id="job-2",
    )
    persist_lane_terminal_event(
        repo,
        result=ExecutionResult(status="success", summary="已交付供应商对比结论"),
        session_id="session-1",
        lane="research",
        task_id="task-2",
        job_id="job-2",
    )

    latest_event = repo.get_latest_task_event("task-2")
    assert latest_event is not None
    assert latest_event["event_type"] == "lane.completed"
    assert latest_event["payload"]["checkpoint"] is True

    snapshot = read_persisted_lane_job(
        repo,
        session_id="session-1",
        lane="research",
        job_id="job-2",
        task_id="task-2",
    )
    assert snapshot is not None
    assert snapshot["latest_job_state"] == "completed"
    assert snapshot["latest_event_type"] == "lane.completed"
    assert snapshot["summary_items"][-1] == "市场部任务已完成：已交付供应商对比结论"
    assert "已交付供应商对比结论" in snapshot["summary"]


def test_cancelled_checkpoint_persists_final_reason(tmp_path):
    repo = SQLiteTaskRepository(db_path=tmp_path / "state.db")

    persist_lane_terminal_event(
        repo,
        result=ExecutionResult(
            status="failed",
            summary="已取消当前调研",
            failure_reason="interrupted_by_user",
        ),
        session_id="session-1",
        lane="research",
        task_id="task-3",
        job_id="job-3",
    )

    latest_event = repo.get_latest_task_event("task-3")
    assert latest_event is not None
    assert latest_event["event_type"] == "lane.cancelled"
    assert latest_event["payload"]["failure_reason"] == "interrupted_by_user"
    assert latest_event["payload"]["checkpoint"] is True

    snapshot = read_persisted_lane_job(
        repo,
        session_id="session-1",
        lane="research",
        job_id="job-3",
        task_id="task-3",
    )
    assert snapshot is not None
    assert snapshot["latest_job_state"] == "cancelled"
    assert snapshot["failure_reason"] == "interrupted_by_user"
    assert snapshot["summary_items"][-1] == "市场部任务已取消：已取消当前调研"


def test_persist_lane_event_without_job_id_creates_readable_snapshot(tmp_path):
    repo = SQLiteTaskRepository(db_path=tmp_path / "state.db")

    persist_lane_progress_event(
        repo,
        event_type="kernel.codex.web_search.started",
        payload={"query": "vendor pricing benchmarks"},
        session_id="session-1",
        lane="research",
        task_id="task-no-job",
        job_id=None,
    )

    latest_event = repo.get_latest_task_event("task-no-job")
    assert latest_event is not None
    assert latest_event["event_type"] == "lane.progress"

    snapshot = read_persisted_lane_job(
        repo,
        session_id="session-1",
        lane="research",
        task_id="task-no-job",
    )
    assert snapshot is not None
    assert snapshot["task_id"] == "task-no-job"
    assert snapshot["job_id"] == "task-no-job"
    assert snapshot["latest_job_state"] == "running"
    assert snapshot["summary_items"] == ["市场部正在检索信息：vendor pricing benchmarks"]
