"""Memory storage abstractions for Mente."""

from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Protocol

from mente.memory.models import MemoryRecord
from mente.task_core.repository import get_default_task_db_path

MENTE_MEMORIES_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS mente_memories (
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

CREATE INDEX IF NOT EXISTS idx_mente_memories_scope_lookup
ON mente_memories(scope, session_id, task_type, score DESC, created_at DESC, memory_id DESC);

CREATE INDEX IF NOT EXISTS idx_mente_memories_source
ON mente_memories(source, scope, score DESC, created_at DESC, memory_id DESC);
"""


class MemoryRepository(Protocol):
    """Persistence interface for memories."""

    def save(self, record: MemoryRecord) -> None:
        """Persist a memory record."""

    def get(self, memory_id: str) -> MemoryRecord | None:
        """Load a memory record by id."""

    def list_recent(
        self,
        limit: int = 20,
        offset: int = 0,
        source: str | None = None,
        task_type: str | None = None,
        memory_scope: str | None = None,
    ) -> list[MemoryRecord]:
        """List the most recent memories across sessions."""

    def list_by_session(
        self,
        session_id: str,
        limit: int = 20,
        offset: int = 0,
        source: str | None = None,
        task_type: str | None = None,
        memory_scope: str | None = None,
    ) -> list[MemoryRecord]:
        """List the most recent memories for a session."""

    def list_relevant(
        self,
        session_id: str | None,
        task_type: str,
        limit: int = 5,
        source: str | None = None,
    ) -> list[MemoryRecord]:
        """Return memories ordered by deterministic relevance."""


def get_default_memory_db_path() -> Path:
    """Resolve the persistent memory DB path."""
    override = os.getenv("MENTE_MEMORY_DB_PATH", "").strip()
    if override:
        return Path(override).expanduser()
    return get_default_task_db_path()


def _scope_rank(record: MemoryRecord, session_id: str | None, task_type: str) -> int:
    if record.scope == "session" and session_id is not None and record.session_id == session_id:
        return 0
    if record.scope == "task_type" and record.task_type == task_type:
        return 1
    if record.scope == "global":
        return 2
    return 99


def _record_sort_key(record: MemoryRecord, session_id: str | None, task_type: str) -> tuple[object, ...]:
    created_at = record.created_at if record.created_at is not None else float("-inf")
    return (
        _scope_rank(record, session_id, task_type),
        -record.score,
        -created_at,
        record.memory_id,
    )


def _debug_sort_key(record: MemoryRecord) -> tuple[object, ...]:
    created_at = record.created_at if record.created_at is not None else float("-inf")
    return (created_at, record.memory_id)


class InMemoryMemoryRepository:
    """Simple in-memory repository for Mente memories."""

    def __init__(self) -> None:
        self._records: dict[str, MemoryRecord] = {}

    def save(self, record: MemoryRecord) -> None:
        if record.created_at is None:
            record = record.model_copy(update={"created_at": time.time()})
        self._records[record.memory_id] = record

    def get(self, memory_id: str) -> MemoryRecord | None:
        return self._records.get(memory_id)

    def list_recent(
        self,
        limit: int = 20,
        offset: int = 0,
        source: str | None = None,
        task_type: str | None = None,
        memory_scope: str | None = None,
    ) -> list[MemoryRecord]:
        if limit <= 0 or offset < 0:
            return []
        records = list(self._records.values())
        if source is not None:
            records = [record for record in records if record.source == source]
        if task_type is not None:
            records = [record for record in records if record.task_type == task_type]
        if memory_scope is not None:
            records = [record for record in records if record.scope == memory_scope]
        records.sort(key=_debug_sort_key, reverse=True)
        return records[offset:offset + limit]

    def list_by_session(
        self,
        session_id: str,
        limit: int = 20,
        offset: int = 0,
        source: str | None = None,
        task_type: str | None = None,
        memory_scope: str | None = None,
    ) -> list[MemoryRecord]:
        if limit <= 0 or offset < 0:
            return []
        records = [
            record
            for record in self._records.values()
            if record.session_id == session_id
        ]
        if source is not None:
            records = [record for record in records if record.source == source]
        if task_type is not None:
            records = [record for record in records if record.task_type == task_type]
        if memory_scope is not None:
            records = [record for record in records if record.scope == memory_scope]
        records.sort(key=_debug_sort_key, reverse=True)
        return records[offset:offset + limit]

    def list_relevant(
        self,
        session_id: str | None,
        task_type: str,
        limit: int = 5,
        source: str | None = None,
    ) -> list[MemoryRecord]:
        if limit <= 0:
            return []
        records = list(self._records.values())
        if source is not None:
            records = [record for record in records if record.source == source]
        records = [
            record
            for record in records
            if _scope_rank(record, session_id, task_type) != 99
        ]
        records.sort(key=lambda record: _record_sort_key(record, session_id, task_type))
        return records[:limit]


class SQLiteMemoryRepository:
    """SQLite-backed repository for persistent Mente memories."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        self.db_path = Path(db_path) if db_path is not None else get_default_memory_db_path()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(
            str(self.db_path),
            check_same_thread=False,
            timeout=1.0,
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.executescript(MENTE_MEMORIES_SCHEMA_SQL)
        self._conn.commit()

    def save(self, record: MemoryRecord) -> None:
        created_at = record.created_at if record.created_at is not None else time.time()
        self._conn.execute(
            """
            INSERT INTO mente_memories (
                memory_id,
                session_id,
                task_id,
                task_type,
                source,
                scope,
                fact,
                kind,
                score,
                metadata_json,
                created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(memory_id) DO UPDATE SET
                session_id = excluded.session_id,
                task_id = excluded.task_id,
                task_type = excluded.task_type,
                source = excluded.source,
                scope = excluded.scope,
                fact = excluded.fact,
                kind = excluded.kind,
                score = excluded.score,
                metadata_json = excluded.metadata_json,
                created_at = excluded.created_at
            """,
            (
                record.memory_id,
                record.session_id,
                record.task_id,
                record.task_type,
                record.source,
                record.scope,
                record.fact,
                record.kind,
                record.score,
                json.dumps(record.metadata, sort_keys=True, separators=(",", ":")),
                created_at,
            ),
        )
        self._conn.commit()

    def get(self, memory_id: str) -> MemoryRecord | None:
        row = self._conn.execute(
            """
            SELECT memory_id, session_id, task_id, task_type, source, scope,
                   fact, kind, score, metadata_json, created_at
            FROM mente_memories
            WHERE memory_id = ?
            """,
            (memory_id,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_record(row)

    def list_recent(
        self,
        limit: int = 20,
        offset: int = 0,
        source: str | None = None,
        task_type: str | None = None,
        memory_scope: str | None = None,
    ) -> list[MemoryRecord]:
        if limit <= 0 or offset < 0:
            return []
        clauses: list[str] = []
        params: list[object] = []
        if source is not None:
            clauses.append("source = ?")
            params.append(source)
        if task_type is not None:
            clauses.append("task_type = ?")
            params.append(task_type)
        if memory_scope is not None:
            clauses.append("scope = ?")
            params.append(memory_scope)
        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.extend([limit, offset])
        rows = self._conn.execute(
            f"""
            SELECT memory_id, session_id, task_id, task_type, source, scope,
                   fact, kind, score, metadata_json, created_at
            FROM mente_memories
            {where_sql}
            ORDER BY created_at DESC, memory_id DESC
            LIMIT ?
            OFFSET ?
            """,
            params,
        ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def list_by_session(
        self,
        session_id: str,
        limit: int = 20,
        offset: int = 0,
        source: str | None = None,
        task_type: str | None = None,
        memory_scope: str | None = None,
    ) -> list[MemoryRecord]:
        if limit <= 0 or offset < 0:
            return []
        clauses = ["session_id = ?"]
        params: list[object] = [session_id]
        if source is not None:
            clauses.append("source = ?")
            params.append(source)
        if task_type is not None:
            clauses.append("task_type = ?")
            params.append(task_type)
        if memory_scope is not None:
            clauses.append("scope = ?")
            params.append(memory_scope)
        params.extend([limit, offset])
        rows = self._conn.execute(
            f"""
            SELECT memory_id, session_id, task_id, task_type, source, scope,
                   fact, kind, score, metadata_json, created_at
            FROM mente_memories
            WHERE {" AND ".join(clauses)}
            ORDER BY created_at DESC, memory_id DESC
            LIMIT ?
            OFFSET ?
            """,
            params,
        ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def list_relevant(
        self,
        session_id: str | None,
        task_type: str,
        limit: int = 5,
        source: str | None = None,
    ) -> list[MemoryRecord]:
        if limit <= 0:
            return []
        clauses = [
            """(
                (scope = 'session' AND session_id = ?)
                OR (scope = 'task_type' AND task_type = ?)
                OR scope = 'global'
            )"""
        ]
        params: list[object] = [session_id, task_type]
        if source is not None:
            clauses.append("source = ?")
            params.append(source)
        params.append(limit)
        rows = self._conn.execute(
            f"""
            SELECT memory_id, session_id, task_id, task_type, source, scope,
                   fact, kind, score, metadata_json, created_at
            FROM mente_memories
            WHERE {" AND ".join(clauses)}
            ORDER BY
                CASE
                    WHEN scope = 'session' AND session_id = ? THEN 0
                    WHEN scope = 'task_type' AND task_type = ? THEN 1
                    WHEN scope = 'global' THEN 2
                    ELSE 99
                END ASC,
                score DESC,
                created_at DESC,
                memory_id DESC
            LIMIT ?
            """,
            [*params[:-1], session_id, task_type, params[-1]],
        ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def close(self) -> None:
        self._conn.close()

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> MemoryRecord:
        return MemoryRecord(
            memory_id=row["memory_id"],
            session_id=row["session_id"],
            task_id=row["task_id"],
            task_type=row["task_type"],
            source=row["source"],
            scope=row["scope"],
            fact=row["fact"],
            kind=row["kind"],
            score=float(row["score"]),
            created_at=float(row["created_at"]),
            metadata=json.loads(row["metadata_json"]),
        )
