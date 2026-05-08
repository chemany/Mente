"""Memory storage abstractions for Mente."""

from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Protocol

from hermes_constants import get_mente_home
from mente.memory.fact_normalization import build_fact_identity
from mente.memory.models import MemoryRecord

MENTE_MEMORIES_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS mente_memories (
    memory_id TEXT PRIMARY KEY,
    session_id TEXT,
    task_id TEXT NOT NULL,
    task_type TEXT NOT NULL,
    source TEXT NOT NULL,
    scope TEXT NOT NULL,
    fact TEXT NOT NULL,
    fact_key TEXT,
    slot_key TEXT,
    active INTEGER NOT NULL DEFAULT 1,
    superseded_by_memory_id TEXT,
    kind TEXT NOT NULL,
    score REAL NOT NULL,
    metadata_json TEXT NOT NULL,
    created_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_mente_memories_scope_lookup
ON mente_memories(scope, session_id, task_type, score DESC, created_at DESC, memory_id DESC);

CREATE INDEX IF NOT EXISTS idx_mente_memories_source
ON mente_memories(source, scope, score DESC, created_at DESC, memory_id DESC);

CREATE INDEX IF NOT EXISTS idx_mente_memories_fact_key_active
ON mente_memories(source, scope, fact_key, active);

CREATE INDEX IF NOT EXISTS idx_mente_memories_slot_key_active
ON mente_memories(source, scope, slot_key, active);
"""


class MemoryRepository(Protocol):
    """Persistence interface for memories."""

    def save(self, record: MemoryRecord) -> None:
        """Persist a memory record."""

    def save_resolved_fact(self, record: MemoryRecord) -> tuple[MemoryRecord, str | None]:
        """Persist one resolved fact with exact-dedup and narrow supersede semantics."""

    def get(self, memory_id: str) -> MemoryRecord | None:
        """Load a memory record by id."""

    def list_recent(
        self,
        limit: int = 20,
        offset: int = 0,
        source: str | None = None,
        task_type: str | None = None,
        memory_scope: str | None = None,
        include_inactive: bool = False,
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
        include_inactive: bool = False,
    ) -> list[MemoryRecord]:
        """List the most recent memories for a session."""

    def list_relevant(
        self,
        session_id: str | None,
        task_type: str,
        limit: int = 5,
        source: str | None = None,
        include_inactive: bool = False,
    ) -> list[MemoryRecord]:
        """Return memories ordered by deterministic relevance."""

    def list_relevant_by_scope(
        self,
        *,
        session_id: str | None,
        task_type: str,
        memory_scope: str,
        limit: int = 5,
        source: str | None = None,
        kind: str | None = None,
        exclude_kinds: tuple[str, ...] | None = None,
        include_inactive: bool = False,
    ) -> list[MemoryRecord]:
        """Return memories for one scope ordered by deterministic relevance."""

    def find_active_exact(
        self,
        *,
        session_id: str | None,
        task_type: str,
        source: str,
        scope: str,
        fact_key: str,
    ) -> MemoryRecord | None:
        """Return one active exact-match record for the same scope."""

    def list_active_by_slot(
        self,
        *,
        session_id: str | None,
        task_type: str,
        source: str,
        scope: str,
        slot_key: str,
    ) -> list[MemoryRecord]:
        """Return active records for one supported slot."""

    def mark_superseded(self, memory_id: str, *, superseded_by_memory_id: str) -> None:
        """Mark one record inactive and point at the replacing row."""


def get_default_memory_db_path() -> Path:
    """Resolve the persistent memory DB path.

    Mente memories must land in the Mente-owned primary state DB so every
    outward entrypoint shares the same memory store.
    """
    override = os.getenv("MENTE_MEMORY_DB_PATH", "").strip()
    if override:
        return Path(override).expanduser()
    return get_mente_home() / "state.db"


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


def _matches_scope(
    record: MemoryRecord,
    *,
    session_id: str | None,
    task_type: str,
    scope: str,
) -> bool:
    if scope == "session":
        return session_id is not None and record.session_id == session_id
    if scope == "task_type":
        return record.task_type == task_type
    if scope == "global":
        return True
    return False


class InMemoryMemoryRepository:
    """Simple in-memory repository for Mente memories."""

    def __init__(self) -> None:
        self._records: dict[str, MemoryRecord] = {}

    def save(self, record: MemoryRecord) -> None:
        record = self._prepare_record(record)
        self._records[record.memory_id] = record

    def save_resolved_fact(self, record: MemoryRecord) -> tuple[MemoryRecord, str | None]:
        record = self._prepare_record(record)
        existing_by_id = self.get(record.memory_id)
        exact = self.find_active_exact(
            session_id=record.session_id,
            task_type=record.task_type,
            source=record.source,
            scope=record.scope,
            fact_key=record.fact_key or "",
        )
        if exact is not None and exact.memory_id != record.memory_id:
            return exact, "duplicate_existing"

        prior_slot_rows: list[MemoryRecord] = []
        if record.slot_key is not None:
            prior_slot_rows = [
                old_record
                for old_record in self.list_active_by_slot(
                    session_id=record.session_id,
                    task_type=record.task_type,
                    source=record.source,
                    scope=record.scope,
                    slot_key=record.slot_key,
                )
                if old_record.memory_id != record.memory_id
            ]

        self._records[record.memory_id] = record
        for old_record in prior_slot_rows:
            self.mark_superseded(
                old_record.memory_id,
                superseded_by_memory_id=record.memory_id,
            )
        if prior_slot_rows:
            return record, "superseded_existing"
        if existing_by_id is not None:
            return record, "refreshed_existing"
        return record, None

    def _prepare_record(self, record: MemoryRecord) -> MemoryRecord:
        if record.fact_key is None or record.slot_key is None:
            identity = build_fact_identity(record.fact)
            record = record.model_copy(
                update={
                    "fact": identity.normalized_fact,
                    "fact_key": record.fact_key or identity.fact_key,
                    "slot_key": record.slot_key or identity.slot_key,
                }
            )
        if record.created_at is None:
            record = record.model_copy(update={"created_at": time.time()})
        return record

    def get(self, memory_id: str) -> MemoryRecord | None:
        return self._records.get(memory_id)

    def list_recent(
        self,
        limit: int = 20,
        offset: int = 0,
        source: str | None = None,
        task_type: str | None = None,
        memory_scope: str | None = None,
        include_inactive: bool = False,
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
        if not include_inactive:
            records = [record for record in records if record.active]
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
        include_inactive: bool = False,
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
        if not include_inactive:
            records = [record for record in records if record.active]
        records.sort(key=_debug_sort_key, reverse=True)
        return records[offset:offset + limit]

    def list_relevant(
        self,
        session_id: str | None,
        task_type: str,
        limit: int = 5,
        source: str | None = None,
        include_inactive: bool = False,
    ) -> list[MemoryRecord]:
        if limit <= 0:
            return []
        records = list(self._records.values())
        if source is not None:
            records = [record for record in records if record.source == source]
        if not include_inactive:
            records = [record for record in records if record.active]
        records = [
            record
            for record in records
            if _scope_rank(record, session_id, task_type) != 99
        ]
        records.sort(key=lambda record: _record_sort_key(record, session_id, task_type))
        return records[:limit]

    def list_relevant_by_scope(
        self,
        *,
        session_id: str | None,
        task_type: str,
        memory_scope: str,
        limit: int = 5,
        source: str | None = None,
        kind: str | None = None,
        exclude_kinds: tuple[str, ...] | None = None,
        include_inactive: bool = False,
    ) -> list[MemoryRecord]:
        if limit <= 0:
            return []
        records = list(self._records.values())
        if source is not None:
            records = [record for record in records if record.source == source]
        if kind is not None:
            records = [record for record in records if record.kind == kind]
        if exclude_kinds:
            records = [record for record in records if record.kind not in exclude_kinds]
        if not include_inactive:
            records = [record for record in records if record.active]
        if memory_scope == "session":
            if session_id is None:
                return []
            records = [
                record
                for record in records
                if record.scope == "session" and record.session_id == session_id
            ]
        elif memory_scope == "task_type":
            records = [
                record
                for record in records
                if record.scope == "task_type" and record.task_type == task_type
            ]
        elif memory_scope == "global":
            records = [record for record in records if record.scope == "global"]
        else:
            return []
        records.sort(key=lambda record: _record_sort_key(record, session_id, task_type))
        return records[:limit]

    def find_active_exact(
        self,
        *,
        session_id: str | None,
        task_type: str,
        source: str,
        scope: str,
        fact_key: str,
    ) -> MemoryRecord | None:
        matches = [
            record
            for record in self._records.values()
            if record.active
            and record.source == source
            and record.scope == scope
            and record.fact_key == fact_key
            and _matches_scope(record, session_id=session_id, task_type=task_type, scope=scope)
        ]
        if not matches:
            return None
        matches.sort(key=_debug_sort_key, reverse=True)
        return matches[0]

    def list_active_by_slot(
        self,
        *,
        session_id: str | None,
        task_type: str,
        source: str,
        scope: str,
        slot_key: str,
    ) -> list[MemoryRecord]:
        matches = [
            record
            for record in self._records.values()
            if record.active
            and record.source == source
            and record.scope == scope
            and record.slot_key == slot_key
            and _matches_scope(record, session_id=session_id, task_type=task_type, scope=scope)
        ]
        matches.sort(key=lambda record: _record_sort_key(record, session_id, task_type))
        return matches

    def mark_superseded(self, memory_id: str, *, superseded_by_memory_id: str) -> None:
        record = self._records.get(memory_id)
        if record is None:
            return
        self._records[memory_id] = record.model_copy(
            update={
                "active": False,
                "superseded_by_memory_id": superseded_by_memory_id,
            }
        )


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
        existing_columns = {
            row["name"]
            for row in self._conn.execute("PRAGMA table_info(mente_memories)").fetchall()
        }
        migrations = {
            "fact_key": "ALTER TABLE mente_memories ADD COLUMN fact_key TEXT",
            "slot_key": "ALTER TABLE mente_memories ADD COLUMN slot_key TEXT",
            "active": "ALTER TABLE mente_memories ADD COLUMN active INTEGER NOT NULL DEFAULT 1",
            "superseded_by_memory_id": "ALTER TABLE mente_memories ADD COLUMN superseded_by_memory_id TEXT",
        }
        for column, statement in migrations.items():
            if column not in existing_columns:
                self._conn.execute(statement)
        self._conn.executescript(
            """
            CREATE INDEX IF NOT EXISTS idx_mente_memories_fact_key_active
            ON mente_memories(source, scope, fact_key, active);

            CREATE INDEX IF NOT EXISTS idx_mente_memories_slot_key_active
            ON mente_memories(source, scope, slot_key, active);
            """
        )
        self._conn.commit()

    def save(self, record: MemoryRecord) -> None:
        record = self._prepare_record(record)
        self._write_record(record)
        self._conn.commit()

    def save_resolved_fact(self, record: MemoryRecord) -> tuple[MemoryRecord, str | None]:
        record = self._prepare_record(record)
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            existing_by_id = self.get(record.memory_id)
            exact = self._find_active_exact_tx(
                session_id=record.session_id,
                task_type=record.task_type,
                source=record.source,
                scope=record.scope,
                fact_key=record.fact_key or "",
            )
            if exact is not None and exact.memory_id != record.memory_id:
                self._conn.rollback()
                return exact, "duplicate_existing"

            prior_slot_rows: list[MemoryRecord] = []
            if record.slot_key is not None:
                prior_slot_rows = [
                    old_record
                    for old_record in self._list_active_by_slot_tx(
                        session_id=record.session_id,
                        task_type=record.task_type,
                        source=record.source,
                        scope=record.scope,
                        slot_key=record.slot_key,
                    )
                    if old_record.memory_id != record.memory_id
                ]

            self._write_record(record)
            if prior_slot_rows:
                self._conn.executemany(
                    """
                    UPDATE mente_memories
                    SET active = 0,
                        superseded_by_memory_id = ?
                    WHERE memory_id = ?
                    """,
                    [(record.memory_id, old_record.memory_id) for old_record in prior_slot_rows],
                )
            self._conn.commit()
            if prior_slot_rows:
                return record, "superseded_existing"
            if existing_by_id is not None:
                return record, "refreshed_existing"
            return record, None
        except Exception:
            self._conn.rollback()
            raise

    def _prepare_record(self, record: MemoryRecord) -> MemoryRecord:
        if record.fact_key is None or record.slot_key is None:
            identity = build_fact_identity(record.fact)
            record = record.model_copy(
                update={
                    "fact": identity.normalized_fact,
                    "fact_key": record.fact_key or identity.fact_key,
                    "slot_key": record.slot_key or identity.slot_key,
                }
            )
        if record.created_at is None:
            record = record.model_copy(update={"created_at": time.time()})
        return record

    def _write_record(self, record: MemoryRecord) -> None:
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
                fact_key,
                slot_key,
                active,
                superseded_by_memory_id,
                kind,
                score,
                metadata_json,
                created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(memory_id) DO UPDATE SET
                session_id = excluded.session_id,
                task_id = excluded.task_id,
                task_type = excluded.task_type,
                source = excluded.source,
                scope = excluded.scope,
                fact = excluded.fact,
                fact_key = excluded.fact_key,
                slot_key = excluded.slot_key,
                active = excluded.active,
                superseded_by_memory_id = excluded.superseded_by_memory_id,
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
                record.fact_key,
                record.slot_key,
                1 if record.active else 0,
                record.superseded_by_memory_id,
                record.kind,
                record.score,
                json.dumps(record.metadata, sort_keys=True, separators=(",", ":")),
                record.created_at,
            ),
        )

    def get(self, memory_id: str) -> MemoryRecord | None:
        row = self._conn.execute(
            """
            SELECT memory_id, session_id, task_id, task_type, source, scope,
                   fact, fact_key, slot_key, active, superseded_by_memory_id,
                   kind, score, metadata_json, created_at
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
        include_inactive: bool = False,
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
        if not include_inactive:
            clauses.append("active = 1")
        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.extend([limit, offset])
        rows = self._conn.execute(
            f"""
            SELECT memory_id, session_id, task_id, task_type, source, scope,
                   fact, fact_key, slot_key, active, superseded_by_memory_id,
                   kind, score, metadata_json, created_at
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
        include_inactive: bool = False,
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
        if not include_inactive:
            clauses.append("active = 1")
        params.extend([limit, offset])
        rows = self._conn.execute(
            f"""
            SELECT memory_id, session_id, task_id, task_type, source, scope,
                   fact, fact_key, slot_key, active, superseded_by_memory_id,
                   kind, score, metadata_json, created_at
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
        include_inactive: bool = False,
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
        if not include_inactive:
            clauses.append("active = 1")
        params.append(limit)
        rows = self._conn.execute(
            f"""
            SELECT memory_id, session_id, task_id, task_type, source, scope,
                   fact, fact_key, slot_key, active, superseded_by_memory_id,
                   kind, score, metadata_json, created_at
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

    def list_relevant_by_scope(
        self,
        *,
        session_id: str | None,
        task_type: str,
        memory_scope: str,
        limit: int = 5,
        source: str | None = None,
        kind: str | None = None,
        exclude_kinds: tuple[str, ...] | None = None,
        include_inactive: bool = False,
    ) -> list[MemoryRecord]:
        if limit <= 0:
            return []

        clauses: list[str] = ["scope = ?"]
        params: list[object] = [memory_scope]
        if memory_scope == "session":
            if session_id is None:
                return []
            clauses.append("session_id = ?")
            params.append(session_id)
        elif memory_scope == "task_type":
            clauses.append("task_type = ?")
            params.append(task_type)
        elif memory_scope != "global":
            return []

        if source is not None:
            clauses.append("source = ?")
            params.append(source)
        if kind is not None:
            clauses.append("kind = ?")
            params.append(kind)
        if exclude_kinds:
            placeholders = ", ".join("?" for _ in exclude_kinds)
            clauses.append(f"kind NOT IN ({placeholders})")
            params.extend(exclude_kinds)
        if not include_inactive:
            clauses.append("active = 1")

        params.append(limit)
        rows = self._conn.execute(
            f"""
            SELECT memory_id, session_id, task_id, task_type, source, scope,
                   fact, fact_key, slot_key, active, superseded_by_memory_id,
                   kind, score, metadata_json, created_at
            FROM mente_memories
            WHERE {" AND ".join(clauses)}
            ORDER BY score DESC, created_at DESC, memory_id DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def find_active_exact(
        self,
        *,
        session_id: str | None,
        task_type: str,
        source: str,
        scope: str,
        fact_key: str,
    ) -> MemoryRecord | None:
        return self._find_active_exact_tx(
            session_id=session_id,
            task_type=task_type,
            source=source,
            scope=scope,
            fact_key=fact_key,
        )

    def _find_active_exact_tx(
        self,
        *,
        session_id: str | None,
        task_type: str,
        source: str,
        scope: str,
        fact_key: str,
    ) -> MemoryRecord | None:
        clauses = [
            "source = ?",
            "scope = ?",
            "fact_key = ?",
            "active = 1",
        ]
        params: list[object] = [source, scope, fact_key]
        if scope == "session":
            clauses.append("session_id = ?")
            params.append(session_id)
        elif scope == "task_type":
            clauses.append("task_type = ?")
            params.append(task_type)
        elif scope != "global":
            return None
        row = self._conn.execute(
            f"""
            SELECT memory_id, session_id, task_id, task_type, source, scope,
                   fact, fact_key, slot_key, active, superseded_by_memory_id,
                   kind, score, metadata_json, created_at
            FROM mente_memories
            WHERE {' AND '.join(clauses)}
            ORDER BY created_at DESC, memory_id DESC
            LIMIT 1
            """,
            params,
        ).fetchone()
        return self._row_to_record(row) if row is not None else None

    def list_active_by_slot(
        self,
        *,
        session_id: str | None,
        task_type: str,
        source: str,
        scope: str,
        slot_key: str,
    ) -> list[MemoryRecord]:
        return self._list_active_by_slot_tx(
            session_id=session_id,
            task_type=task_type,
            source=source,
            scope=scope,
            slot_key=slot_key,
        )

    def _list_active_by_slot_tx(
        self,
        *,
        session_id: str | None,
        task_type: str,
        source: str,
        scope: str,
        slot_key: str,
    ) -> list[MemoryRecord]:
        clauses = [
            "source = ?",
            "scope = ?",
            "slot_key = ?",
            "active = 1",
        ]
        params: list[object] = [source, scope, slot_key]
        if scope == "session":
            clauses.append("session_id = ?")
            params.append(session_id)
        elif scope == "task_type":
            clauses.append("task_type = ?")
            params.append(task_type)
        elif scope != "global":
            return []
        rows = self._conn.execute(
            f"""
            SELECT memory_id, session_id, task_id, task_type, source, scope,
                   fact, fact_key, slot_key, active, superseded_by_memory_id,
                   kind, score, metadata_json, created_at
            FROM mente_memories
            WHERE {' AND '.join(clauses)}
            ORDER BY score DESC, created_at DESC, memory_id DESC
            """,
            params,
        ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def mark_superseded(self, memory_id: str, *, superseded_by_memory_id: str) -> None:
        self._conn.execute(
            """
            UPDATE mente_memories
            SET active = 0,
                superseded_by_memory_id = ?
            WHERE memory_id = ?
            """,
            (superseded_by_memory_id, memory_id),
        )
        self._conn.commit()

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
            fact_key=row["fact_key"],
            slot_key=row["slot_key"],
            active=bool(row["active"]),
            superseded_by_memory_id=row["superseded_by_memory_id"],
            kind=row["kind"],
            score=float(row["score"]),
            created_at=float(row["created_at"]),
            metadata=json.loads(row["metadata_json"]),
        )
