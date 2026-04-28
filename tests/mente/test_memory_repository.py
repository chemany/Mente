from mente.memory.models import MemoryRecord
from mente.memory.repository import InMemoryMemoryRepository, SQLiteMemoryRepository


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


def test_in_memory_memory_repository_list_recent_filters_and_offset():
    repo = InMemoryMemoryRepository()
    repo.save(
        MemoryRecord(
            memory_id="mem_1",
            session_id="sess-a",
            task_id="task_1",
            task_type="conversation",
            source="gateway",
            scope="session",
            fact="Older gateway fact",
            created_at=1000.0,
        )
    )
    repo.save(
        MemoryRecord(
            memory_id="mem_2",
            session_id="sess-a",
            task_id="task_2",
            task_type="conversation",
            source="gateway",
            scope="session",
            fact="Newer gateway fact",
            created_at=1001.0,
        )
    )
    repo.save(
        MemoryRecord(
            memory_id="mem_3",
            session_id="sess-b",
            task_id="task_3",
            task_type="cron",
            source="cron",
            scope="task_type",
            fact="Cron fact",
            created_at=1002.0,
        )
    )

    rows = repo.list_recent(limit=1, offset=1, source="gateway")
    assert [row.memory_id for row in rows] == ["mem_1"]


def test_sqlite_memory_repository_list_recent_filters_and_offset(tmp_path, monkeypatch):
    db_path = tmp_path / "memory.db"
    repo = SQLiteMemoryRepository(db_path=db_path)
    timestamps = iter([1000.0, 1001.0, 1002.0])
    monkeypatch.setattr("mente.memory.repository.time.time", lambda: next(timestamps))

    repo.save(
        MemoryRecord(
            memory_id="mem_1",
            session_id="sess-a",
            task_id="task_1",
            task_type="conversation",
            source="gateway",
            scope="session",
            fact="Older gateway fact",
        )
    )
    repo.save(
        MemoryRecord(
            memory_id="mem_2",
            session_id="sess-a",
            task_id="task_2",
            task_type="conversation",
            source="gateway",
            scope="session",
            fact="Newer gateway fact",
        )
    )
    repo.save(
        MemoryRecord(
            memory_id="mem_3",
            session_id="sess-b",
            task_id="task_3",
            task_type="cron",
            source="cron",
            scope="task_type",
            fact="Cron fact",
        )
    )

    rows = repo.list_recent(limit=1, offset=1, source="gateway")
    assert [row.memory_id for row in rows] == ["mem_1"]


def test_sqlite_memory_repository_list_by_session_filters_scope_and_task_type(tmp_path):
    db_path = tmp_path / "memory.db"
    repo = SQLiteMemoryRepository(db_path=db_path)
    repo.save(
        MemoryRecord(
            memory_id="mem_session",
            session_id="sess-1",
            task_id="task_1",
            task_type="conversation",
            source="gateway",
            scope="session",
            fact="Session fact",
        )
    )
    repo.save(
        MemoryRecord(
            memory_id="mem_task_type",
            session_id="sess-1",
            task_id="task_2",
            task_type="cron",
            source="cron",
            scope="task_type",
            fact="Wrong type",
        )
    )

    rows = repo.list_by_session(
        "sess-1",
        task_type="conversation",
        memory_scope="session",
    )
    assert [row.memory_id for row in rows] == ["mem_session"]
