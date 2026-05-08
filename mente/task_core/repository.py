"""Task storage abstractions for Mente."""

from __future__ import annotations

import os
import sqlite3
import time
from pathlib import Path
from typing import Protocol

from hermes_constants import get_mente_home
from mente.task_core.models import Task

MENTE_TASKS_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS mente_tasks (
    task_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    task_type TEXT NOT NULL,
    status TEXT NOT NULL,
    objective TEXT NOT NULL,
    user_request TEXT NOT NULL,
    workspace TEXT,
    source TEXT,
    payload_json TEXT NOT NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_mente_tasks_session_id
ON mente_tasks(session_id, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_mente_tasks_status
ON mente_tasks(status, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_mente_tasks_source
ON mente_tasks(source, updated_at DESC);
"""


class TaskRepository(Protocol):
    """Persistence interface for tasks."""

    def save(self, task: Task) -> None:
        """Persist a task."""

    def get(self, task_id: str) -> Task | None:
        """Load a task by id."""

    def list_by_session(
        self,
        session_id: str,
        limit: int = 20,
        offset: int = 0,
        source: str | None = None,
        status: str | None = None,
        task_type: str | None = None,
    ) -> list[Task]:
        """List the most recent tasks for a session."""

    def list_recent(
        self,
        limit: int = 20,
        offset: int = 0,
        source: str | None = None,
        status: str | None = None,
        task_type: str | None = None,
    ) -> list[Task]:
        """List the most recent tasks across sessions."""


class InMemoryTaskRepository:
    """Simple in-memory repository for early Mente runtime development."""

    def __init__(self) -> None:
        self._tasks: dict[str, Task] = {}

    def save(self, task: Task) -> None:
        self._tasks[task.task_id] = task

    def get(self, task_id: str) -> Task | None:
        return self._tasks.get(task_id)

    def list_by_session(
        self,
        session_id: str,
        limit: int = 20,
        offset: int = 0,
        source: str | None = None,
        status: str | None = None,
        task_type: str | None = None,
    ) -> list[Task]:
        if limit <= 0 or offset < 0:
            return []
        tasks = [task for task in self._tasks.values() if task.session_id == session_id]
        if source is not None:
            tasks = [task for task in tasks if str(task.metadata.get("source") or "") == source]
        if status is not None:
            tasks = [task for task in tasks if task.status.value == status]
        if task_type is not None:
            tasks = [task for task in tasks if task.task_type == task_type]
        ordered = list(reversed(tasks))
        return ordered[offset:offset + limit]

    def list_recent(
        self,
        limit: int = 20,
        offset: int = 0,
        source: str | None = None,
        status: str | None = None,
        task_type: str | None = None,
    ) -> list[Task]:
        if limit <= 0 or offset < 0:
            return []
        tasks = list(self._tasks.values())
        if source is not None:
            tasks = [task for task in tasks if str(task.metadata.get("source") or "") == source]
        if status is not None:
            tasks = [task for task in tasks if task.status.value == status]
        if task_type is not None:
            tasks = [task for task in tasks if task.task_type == task_type]
        ordered = list(reversed(tasks))
        return ordered[offset:offset + limit]


def get_default_task_db_path() -> Path:
    """Resolve the persistent task DB path.

    Mente task records must live in the Mente-owned primary state DB so
    TUI, gateway, and oneshot all share one session/task timeline.
    """
    override = os.getenv("MENTE_TASK_DB_PATH", "").strip()
    if override:
        return Path(override).expanduser()
    return get_mente_home() / "state.db"


class SQLiteTaskRepository:
    """SQLite-backed task repository for persistent Mente task records."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        self.db_path = Path(db_path) if db_path is not None else get_default_task_db_path()
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
        self._conn.executescript(MENTE_TASKS_SCHEMA_SQL)
        self._conn.commit()

    def save(self, task: Task) -> None:
        now = time.time()
        existing = self._conn.execute(
            "SELECT created_at FROM mente_tasks WHERE task_id = ?",
            (task.task_id,),
        ).fetchone()
        created_at = (
            float(existing["created_at"])
            if existing is not None
            else now
        )
        payload_json = task.model_dump_json()
        self._conn.execute(
            """
            INSERT INTO mente_tasks (
                task_id,
                session_id,
                task_type,
                status,
                objective,
                user_request,
                workspace,
                source,
                payload_json,
                created_at,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(task_id) DO UPDATE SET
                session_id = excluded.session_id,
                task_type = excluded.task_type,
                status = excluded.status,
                objective = excluded.objective,
                user_request = excluded.user_request,
                workspace = excluded.workspace,
                source = excluded.source,
                payload_json = excluded.payload_json,
                updated_at = excluded.updated_at
            """,
            (
                task.task_id,
                task.session_id,
                task.task_type,
                task.status.value,
                task.objective,
                task.user_request,
                task.workspace,
                str(task.metadata.get("source") or ""),
                payload_json,
                created_at,
                now,
            ),
        )
        self._conn.commit()

    def get(self, task_id: str) -> Task | None:
        row = self._conn.execute(
            "SELECT payload_json FROM mente_tasks WHERE task_id = ?",
            (task_id,),
        ).fetchone()
        if row is None:
            return None
        return Task.model_validate_json(row["payload_json"])

    def list_by_session(
        self,
        session_id: str,
        limit: int = 20,
        offset: int = 0,
        source: str | None = None,
        status: str | None = None,
        task_type: str | None = None,
    ) -> list[Task]:
        if limit <= 0 or offset < 0:
            return []
        clauses = ["session_id = ?"]
        params: list[object] = [session_id]
        if source is not None:
            clauses.append("source = ?")
            params.append(source)
        if status is not None:
            clauses.append("status = ?")
            params.append(status)
        if task_type is not None:
            clauses.append("task_type = ?")
            params.append(task_type)
        params.extend([limit, offset])
        rows = self._conn.execute(
            f"""
            SELECT payload_json
            FROM mente_tasks
            WHERE {" AND ".join(clauses)}
            ORDER BY updated_at DESC, created_at DESC, task_id DESC
            LIMIT ?
            OFFSET ?
            """,
            params,
        ).fetchall()
        return [Task.model_validate_json(row["payload_json"]) for row in rows]

    def list_recent(
        self,
        limit: int = 20,
        offset: int = 0,
        source: str | None = None,
        status: str | None = None,
        task_type: str | None = None,
    ) -> list[Task]:
        if limit <= 0 or offset < 0:
            return []
        clauses: list[str] = []
        params: list[object] = []
        if source is not None:
            clauses.append("source = ?")
            params.append(source)
        if status is not None:
            clauses.append("status = ?")
            params.append(status)
        if task_type is not None:
            clauses.append("task_type = ?")
            params.append(task_type)
        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.extend([limit, offset])
        rows = self._conn.execute(
            f"""
            SELECT payload_json
            FROM mente_tasks
            {where_sql}
            ORDER BY updated_at DESC, created_at DESC, task_id DESC
            LIMIT ?
            OFFSET ?
            """,
            params,
        ).fetchall()
        return [Task.model_validate_json(row["payload_json"]) for row in rows]

    def close(self) -> None:
        self._conn.close()
