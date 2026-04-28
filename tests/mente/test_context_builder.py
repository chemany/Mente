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


def test_context_builder_injects_relevant_memory_in_stable_order():
    repo = InMemoryMemoryRepository()
    repo.save(
        MemoryRecord(
            memory_id="mem_session",
            session_id="session_1",
            task_id="task_old",
            task_type="conversation",
            source="gateway",
            scope="session",
            fact="User prefers concise replies.",
        )
    )
    builder = ContextBuilder(memory_repository=repo, memory_limit=5)
    task = Task(
        task_id="task_1",
        session_id="session_1",
        task_type="conversation",
        objective="Reply",
        user_request="Reply",
    )
    request = builder.build(task)
    assert request.memory_facts[0] == "Memory: User prefers concise replies."
