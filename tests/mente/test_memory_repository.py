from mente.memory.models import MemoryRecord
from mente.memory.repository import InMemoryMemoryRepository


def test_memory_repository_round_trip():
    repo = InMemoryMemoryRepository()
    record = MemoryRecord(
        memory_id="mem_1",
        session_id="session_1",
        task_id="task_1",
        task_type="conversation",
        source="gateway",
        scope="session",
        fact="User prefers concise replies.",
    )
    repo.save(record)
    rows = repo.list_relevant(session_id="session_1", task_type="conversation", limit=5)
    assert [row.fact for row in rows] == ["User prefers concise replies."]
