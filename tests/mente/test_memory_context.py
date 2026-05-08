from mente.memory.context import persist_explicit_memory_write
from mente.memory.repository import InMemoryMemoryRepository
from mente.task_core.models import Task


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
