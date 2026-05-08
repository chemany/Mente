from mente.memory.models import MemoryRecord
from mente.memory.repository import InMemoryMemoryRepository, SQLiteMemoryRepository
import sqlite3


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


def test_in_memory_memory_repository_list_relevant_by_scope_filters_kind():
    repo = InMemoryMemoryRepository()
    repo.save(
        MemoryRecord(
            memory_id="mem_summary",
            session_id="sess-1",
            task_id="task_1",
            task_type="conversation",
            source="api_server",
            scope="session",
            kind="session_summary",
            fact="Summary fact",
            score=2.0,
        )
    )
    repo.save(
        MemoryRecord(
            memory_id="mem_fact",
            session_id="sess-1",
            task_id="task_2",
            task_type="conversation",
            source="api_server",
            scope="session",
            kind="fact",
            fact="Ordinary fact",
            score=5.0,
        )
    )

    rows = repo.list_relevant_by_scope(
        session_id="sess-1",
        task_type="conversation",
        memory_scope="session",
        kind="session_summary",
    )

    assert [row.memory_id for row in rows] == ["mem_summary"]


def test_sqlite_memory_repository_list_relevant_by_scope_filters_kind(tmp_path):
    db_path = tmp_path / "memory.db"
    repo = SQLiteMemoryRepository(db_path=db_path)
    repo.save(
        MemoryRecord(
            memory_id="mem_summary",
            session_id="sess-1",
            task_id="task_1",
            task_type="conversation",
            source="api_server",
            scope="session",
            kind="session_summary",
            fact="Summary fact",
            score=2.0,
        )
    )
    repo.save(
        MemoryRecord(
            memory_id="mem_fact",
            session_id="sess-1",
            task_id="task_2",
            task_type="conversation",
            source="api_server",
            scope="session",
            kind="fact",
            fact="Ordinary fact",
            score=5.0,
        )
    )

    rows = repo.list_relevant_by_scope(
        session_id="sess-1",
        task_type="conversation",
        memory_scope="session",
        kind="session_summary",
    )

    assert [row.memory_id for row in rows] == ["mem_summary"]


def test_in_memory_memory_repository_list_relevant_by_scope_excludes_kinds():
    repo = InMemoryMemoryRepository()
    repo.save(
        MemoryRecord(
            memory_id="mem_summary",
            session_id="sess-1",
            task_id="task_1",
            task_type="conversation",
            source="api_server",
            scope="session",
            kind="session_summary",
            fact="Summary fact",
            score=9.0,
        )
    )
    repo.save(
        MemoryRecord(
            memory_id="mem_fact",
            session_id="sess-1",
            task_id="task_2",
            task_type="conversation",
            source="api_server",
            scope="session",
            kind="fact",
            fact="Ordinary fact",
            score=5.0,
        )
    )

    rows = repo.list_relevant_by_scope(
        session_id="sess-1",
        task_type="conversation",
        memory_scope="session",
        limit=1,
        exclude_kinds=("session_summary",),
    )

    assert [row.memory_id for row in rows] == ["mem_fact"]


def test_sqlite_memory_repository_list_relevant_by_scope_excludes_kinds(tmp_path):
    db_path = tmp_path / "memory.db"
    repo = SQLiteMemoryRepository(db_path=db_path)
    repo.save(
        MemoryRecord(
            memory_id="mem_summary",
            session_id="sess-1",
            task_id="task_1",
            task_type="conversation",
            source="api_server",
            scope="session",
            kind="session_summary",
            fact="Summary fact",
            score=9.0,
        )
    )
    repo.save(
        MemoryRecord(
            memory_id="mem_fact",
            session_id="sess-1",
            task_id="task_2",
            task_type="conversation",
            source="api_server",
            scope="session",
            kind="fact",
            fact="Ordinary fact",
            score=5.0,
        )
    )

    rows = repo.list_relevant_by_scope(
        session_id="sess-1",
        task_type="conversation",
        memory_scope="session",
        limit=1,
        exclude_kinds=("session_summary",),
    )

    assert [row.memory_id for row in rows] == ["mem_fact"]


def test_sqlite_memory_repository_find_active_exact_matches_by_fact_key(tmp_path):
    db_path = tmp_path / "memory.db"
    repo = SQLiteMemoryRepository(db_path=db_path)
    repo.save(
        MemoryRecord(
            memory_id="mem_1",
            session_id="sess-1",
            task_id="task_1",
            task_type="conversation",
            source="gateway",
            scope="session",
            fact="我喜欢简洁回答",
            fact_key="fact-key-1",
            active=True,
        )
    )

    row = repo.find_active_exact(
        session_id="sess-1",
        task_type="conversation",
        source="gateway",
        scope="session",
        fact_key="fact-key-1",
    )

    assert row is not None
    assert row.memory_id == "mem_1"


def test_sqlite_memory_repository_migrates_legacy_table_before_creating_new_indexes(
    tmp_path,
):
    db_path = tmp_path / "memory.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE mente_memories (
            memory_id TEXT PRIMARY KEY,
            session_id TEXT,
            task_id TEXT NOT NULL,
            task_type TEXT NOT NULL,
            source TEXT NOT NULL,
            scope TEXT NOT NULL,
            fact TEXT NOT NULL,
            kind TEXT NOT NULL,
            score REAL NOT NULL,
            metadata_json TEXT NOT NULL,
            created_at REAL NOT NULL
        );
        CREATE INDEX idx_mente_memories_scope_lookup
        ON mente_memories(scope, session_id, task_type, score DESC, created_at DESC, memory_id DESC);
        CREATE INDEX idx_mente_memories_source
        ON mente_memories(source, scope, score DESC, created_at DESC, memory_id DESC);
        """
    )
    conn.commit()
    conn.close()

    repo = SQLiteMemoryRepository(db_path=db_path)
    columns = {
        row[1]
        for row in repo._conn.execute("PRAGMA table_info(mente_memories)").fetchall()
    }

    assert {"fact_key", "slot_key", "active", "superseded_by_memory_id"} <= columns


def test_in_memory_memory_repository_save_resolved_fact_returns_existing_duplicate():
    repo = InMemoryMemoryRepository()
    first = MemoryRecord(
        memory_id="mem_1",
        session_id="sess-1",
        task_id="task_1",
        task_type="conversation",
        source="gateway",
        scope="session",
        fact="记住我喜欢简洁回答",
    )
    second = MemoryRecord(
        memory_id="mem_2",
        session_id="sess-1",
        task_id="task_2",
        task_type="conversation",
        source="gateway",
        scope="session",
        fact="我喜欢简洁回答",
    )

    stored_first, first_reason = repo.save_resolved_fact(first)
    stored_second, second_reason = repo.save_resolved_fact(second)

    assert first_reason is None
    assert stored_first.memory_id == "mem_1"
    assert second_reason == "duplicate_existing"
    assert stored_second.memory_id == "mem_1"
    assert [row.memory_id for row in repo.list_by_session("sess-1", source="gateway")] == ["mem_1"]


def test_in_memory_memory_repository_save_resolved_fact_refreshes_same_memory_id():
    repo = InMemoryMemoryRepository()
    first = MemoryRecord(
        memory_id="session_summary:api_server:sess-1:api_server_conversation",
        session_id="sess-1",
        task_id="task_1",
        task_type="conversation",
        source="api_server",
        scope="session",
        fact="Session summary:\n- Recent completed work: Captured the rollout constraints.",
        kind="session_summary",
        metadata={"source_task_id": "task_1", "window_task_ids": ["task_1"]},
    )
    second = MemoryRecord(
        memory_id="session_summary:api_server:sess-1:api_server_conversation",
        session_id="sess-1",
        task_id="task_2",
        task_type="conversation",
        source="api_server",
        scope="session",
        fact="Session summary:\n- Recent completed work: Captured the rollout constraints.",
        kind="session_summary",
        metadata={"source_task_id": "task_2", "window_task_ids": ["task_2"]},
    )

    stored_first, first_reason = repo.save_resolved_fact(first)
    stored_second, second_reason = repo.save_resolved_fact(second)
    refreshed = repo.get(second.memory_id)

    assert first_reason is None
    assert stored_first.task_id == "task_1"
    assert second_reason == "refreshed_existing"
    assert stored_second.task_id == "task_2"
    assert refreshed is not None
    assert refreshed.task_id == "task_2"
    assert refreshed.metadata["source_task_id"] == "task_2"
    assert refreshed.metadata["window_task_ids"] == ["task_2"]


def test_sqlite_memory_repository_save_resolved_fact_supersedes_prior_active_slot(tmp_path):
    db_path = tmp_path / "memory.db"
    repo = SQLiteMemoryRepository(db_path=db_path)
    old = MemoryRecord(
        memory_id="mem_old",
        session_id="sess-1",
        task_id="task_1",
        task_type="conversation",
        source="gateway",
        scope="session",
        fact="我喜欢英文回答",
        slot_key="preference:response_language",
        fact_key="fact-old",
        active=True,
    )
    new = MemoryRecord(
        memory_id="mem_new",
        session_id="sess-1",
        task_id="task_2",
        task_type="conversation",
        source="gateway",
        scope="session",
        fact="我更喜欢中文回答",
        slot_key="preference:response_language",
        fact_key="fact-new",
        active=True,
    )

    stored_old, old_reason = repo.save_resolved_fact(old)
    stored_new, new_reason = repo.save_resolved_fact(new)
    active_rows = repo.list_by_session("sess-1", source="gateway", include_inactive=False)
    superseded_row = repo.get("mem_old")

    assert old_reason is None
    assert stored_old.memory_id == "mem_old"
    assert new_reason == "superseded_existing"
    assert stored_new.memory_id == "mem_new"
    assert [row.memory_id for row in active_rows] == ["mem_new"]
    assert superseded_row is not None
    assert superseded_row.active is False
    assert superseded_row.superseded_by_memory_id == "mem_new"


def test_sqlite_memory_repository_save_resolved_fact_refreshes_same_memory_id(tmp_path):
    db_path = tmp_path / "memory.db"
    repo = SQLiteMemoryRepository(db_path=db_path)
    first = MemoryRecord(
        memory_id="session_summary:api_server:sess-1:api_server_conversation",
        session_id="sess-1",
        task_id="task_1",
        task_type="conversation",
        source="api_server",
        scope="session",
        fact="Session summary:\n- Recent completed work: Captured the rollout constraints.",
        kind="session_summary",
        metadata={"source_task_id": "task_1", "window_task_ids": ["task_1"]},
    )
    second = MemoryRecord(
        memory_id="session_summary:api_server:sess-1:api_server_conversation",
        session_id="sess-1",
        task_id="task_2",
        task_type="conversation",
        source="api_server",
        scope="session",
        fact="Session summary:\n- Recent completed work: Captured the rollout constraints.",
        kind="session_summary",
        metadata={"source_task_id": "task_2", "window_task_ids": ["task_2"]},
    )

    stored_first, first_reason = repo.save_resolved_fact(first)
    stored_second, second_reason = repo.save_resolved_fact(second)
    refreshed = repo.get(second.memory_id)

    assert first_reason is None
    assert stored_first.task_id == "task_1"
    assert second_reason == "refreshed_existing"
    assert stored_second.task_id == "task_2"
    assert refreshed is not None
    assert refreshed.task_id == "task_2"
    assert refreshed.metadata["source_task_id"] == "task_2"
    assert refreshed.metadata["window_task_ids"] == ["task_2"]


def test_sqlite_memory_repository_supersede_marks_old_row_inactive(tmp_path):
    db_path = tmp_path / "memory.db"
    repo = SQLiteMemoryRepository(db_path=db_path)
    repo.save(
        MemoryRecord(
            memory_id="mem_old",
            session_id="sess-1",
            task_id="task_1",
            task_type="conversation",
            source="gateway",
            scope="session",
            fact="我喜欢英文回答",
            slot_key="preference:response_language",
            fact_key="fact-old",
            active=True,
        )
    )
    repo.save(
        MemoryRecord(
            memory_id="mem_new",
            session_id="sess-1",
            task_id="task_2",
            task_type="conversation",
            source="gateway",
            scope="session",
            fact="我更喜欢中文回答",
            slot_key="preference:response_language",
            fact_key="fact-new",
            active=True,
        )
    )

    repo.mark_superseded("mem_old", superseded_by_memory_id="mem_new")

    active_rows = repo.list_by_session("sess-1", source="gateway", include_inactive=False)
    superseded_row = repo.get("mem_old")

    assert [row.memory_id for row in active_rows] == ["mem_new"]
    assert superseded_row is not None
    assert superseded_row.active is False
    assert superseded_row.superseded_by_memory_id == "mem_new"


def test_list_relevant_excludes_inactive_rows():
    repo = InMemoryMemoryRepository()
    repo.save(
        MemoryRecord(
            memory_id="mem_old",
            session_id="sess-1",
            task_id="task_1",
            task_type="conversation",
            source="gateway",
            scope="session",
            fact="我喜欢英文回答",
            slot_key="preference:response_language",
            fact_key="fact-old",
            score=5.0,
            active=False,
            superseded_by_memory_id="mem_new",
        )
    )
    repo.save(
        MemoryRecord(
            memory_id="mem_new",
            session_id="sess-1",
            task_id="task_2",
            task_type="conversation",
            source="gateway",
            scope="session",
            fact="我更喜欢中文回答",
            slot_key="preference:response_language",
            fact_key="fact-new",
            score=1.0,
            active=True,
        )
    )

    rows = repo.list_relevant(session_id="sess-1", task_type="conversation", limit=5, source="gateway")

    assert [row.memory_id for row in rows] == ["mem_new"]
