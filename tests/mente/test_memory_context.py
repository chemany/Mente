from mente.memory.context import persist_explicit_memory_write
from mente.memory.repository import InMemoryMemoryRepository
from mente.review.worker_summary_cache import (
    build_worker_summary_artifact,
    build_worker_summary_memory_id,
)
from mente.task_core.models import ExecutionResult, Task, TaskRole


def test_tui_explicit_memory_write_defaults_to_session_scope():
    repo = InMemoryMemoryRepository()
    task = Task(
        task_id="task_tui_write_1",
        session_id="tui-session-1",
        task_type="conversation",
        objective="Reply",
        user_request="Remember that I prefer concise replies.",
        metadata={"source": "tui"},
    )

    record, reason = persist_explicit_memory_write(
        task,
        fact="User prefers concise replies.",
        memory_repository=repo,
    )

    assert reason is None
    assert record is not None
    assert record.scope == "session"
    assert record.session_id == "tui-session-1"


def test_worker_summary_cache_builders_use_stable_lane_key_and_bounded_artifact():
    task = Task(
        task_id="task_worker_summary_1",
        session_id="gateway-session-1",
        task_type="conversation",
        objective="Continue delegated engineering work",
        user_request="Continue delegated engineering work",
        role=TaskRole.WORKER,
        worker_lane="Engineering",
        metadata={"source": "gateway"},
    )
    result = ExecutionResult(
        status="success",
        summary="Patched the parser and re-ran focused tests.",
        actions_taken=["Patched parser edge case", "Ran focused tests"],
        follow_up_tasks=["Run the broader suite"],
        changed_files=["parser.py"],
        artifacts_out=["/tmp/parser-report.md"],
    )

    artifact = build_worker_summary_artifact(task, result)

    assert build_worker_summary_memory_id(task) == (
        "worker_lane_summary:gateway:gateway-session-1:engineering"
    )
    assert artifact == {
        "artifact_version": "v1",
        "lane": "engineering",
        "status": "success",
        "assistant_summary": "Patched the parser and re-ran focused tests.",
        "actions_taken": ["Patched parser edge case", "Ran focused tests"],
        "follow_up_tasks": ["Run the broader suite"],
        "changed_files": ["parser.py"],
        "artifacts_out": ["/tmp/parser-report.md"],
    }
