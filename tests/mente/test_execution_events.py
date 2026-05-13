from mente.execution_events import (
    build_lane_terminal_event,
    normalize_lane_progress_event,
    render_lane_progress_text,
)
from mente.task_core.models import ExecutionResult


def test_normalize_lane_progress_event_from_command_started():
    normalized = normalize_lane_progress_event(
        "kernel.codex.command.started",
        {"command": '/bin/bash -lc \'sed -n "1,40p" README.md\''},
        lane="engineering",
        task_id="task-1",
    )

    assert normalized is not None
    event_type, payload = normalized
    assert event_type == "lane.progress"
    assert payload["lane"] == "engineering"
    assert payload["task_id"] == "task-1"
    assert payload["status"] == "running"
    assert payload["headline"] == "正在执行"
    assert payload["detail"] == "Bash · sed README.md"
    assert payload["changed_files"] == []
    assert payload["artifacts"] == []
    assert isinstance(payload["timestamp"], str)


def test_normalize_lane_progress_event_from_failed_tool_completion():
    normalized = normalize_lane_progress_event(
        "kernel.codex.mcp_tool.completed",
        {"tool": "mcp__mente__mente_memory_query", "error": "timeout"},
        lane="research",
        task_id="task-2",
    )

    assert normalized is not None
    event_type, payload = normalized
    assert event_type == "lane.blocked"
    assert payload["lane"] == "research"
    assert payload["status"] == "blocked"
    assert payload["headline"] == "工具执行失败"
    assert payload["detail"] == "mente_memory_query"


def test_build_lane_terminal_event_from_success_result():
    result = ExecutionResult(
        status="success",
        summary="done",
        changed_files=["mente/executors/prompting.py"],
        artifacts_out=["reports/output.md"],
    )

    event_type, payload = build_lane_terminal_event(
        result,
        lane="writing",
        task_id="task-3",
    )

    assert event_type == "lane.completed"
    assert payload["lane"] == "writing"
    assert payload["status"] == "completed"
    assert payload["headline"] == "任务已完成"
    assert payload["changed_files"] == ["mente/executors/prompting.py"]
    assert payload["artifacts"] == ["reports/output.md"]
    assert payload["detail"] == "done"


def test_render_lane_progress_text_uses_department_voice():
    text = render_lane_progress_text(
        "lane.progress",
        {
            "lane": "research",
            "headline": "正在执行",
            "detail": "Bash · rg agent.log",
        },
    )

    assert text == "市场部正在执行：Bash · rg agent.log"
