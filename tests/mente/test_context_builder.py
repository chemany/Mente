from mente.context_builder.builder import ContextBuilder
from mente.memory.models import MemoryRecord
from mente.memory.repository import InMemoryMemoryRepository
from mente.task_core.models import Task


def test_context_builder_produces_execution_request():
    builder = ContextBuilder()
    task = Task(
        task_id="task_1",
        session_id="session_1",
        task_type="engineering",
        objective="Inspect repository",
        user_request="Inspect repository",
    )
    request = builder.build(task)
    assert request.task_id == "task_1"
    assert request.objective == "Inspect repository"


def test_context_builder_prepends_retrieved_memory():
    memory_repo = InMemoryMemoryRepository()
    memory_repo.save(
        MemoryRecord(
            memory_id="mem_1",
            session_id="session_1",
            task_id="task_old",
            task_type="conversation",
            source="gateway",
            scope="session",
            fact="User prefers concise replies.",
        )
    )
    task = Task(
        task_id="task_1",
        session_id="session_1",
        task_type="conversation",
        objective="Reply",
        user_request="Reply",
        memory_facts=["Session context: existing"],
    )
    request = ContextBuilder(memory_repository=memory_repo, memory_limit=5).build(task)
    assert request.memory_facts == [
        "Memory: User prefers concise replies.",
        "Session context: existing",
    ]


def test_context_builder_build_with_trace_reports_selected_and_skipped():
    memory_repo = InMemoryMemoryRepository()
    memory_repo.save(
        MemoryRecord(
            memory_id="mem_1",
            session_id="session_1",
            task_id="task_old_1",
            task_type="conversation",
            source="gateway",
            scope="session",
            fact="User prefers concise replies.",
        )
    )
    memory_repo.save(
        MemoryRecord(
            memory_id="mem_2",
            session_id="session_1",
            task_id="task_old_2",
            task_type="conversation",
            source="gateway",
            scope="session",
            fact="Session context: existing",
        )
    )

    task = Task(
        task_id="task_1",
        session_id="session_1",
        task_type="conversation",
        objective="Reply",
        user_request="Reply",
        memory_facts=["Session context: existing"],
    )

    request, trace = ContextBuilder(
        memory_repository=memory_repo,
        memory_limit=5,
    ).build_with_trace(task)

    assert request.memory_facts == [
        "Memory: User prefers concise replies.",
        "Session context: existing",
    ]
    assert trace.injected_count == 1
    assert [item.memory_id for item in trace.selected] == ["mem_1"]
    assert [(item.memory_id, item.reason) for item in trace.skipped] == [
        ("mem_2", "duplicate_existing_fact"),
    ]
