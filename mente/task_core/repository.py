"""Task storage abstractions for Mente."""

from __future__ import annotations

import json
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

CREATE TABLE IF NOT EXISTS mente_session_jobs (
    session_id TEXT NOT NULL,
    lane TEXT NOT NULL,
    job_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    status TEXT NOT NULL,
    summary TEXT NOT NULL,
    requested_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    skill_refs_json TEXT NOT NULL,
    metadata_json TEXT NOT NULL,
    PRIMARY KEY (session_id, lane)
);

CREATE INDEX IF NOT EXISTS idx_mente_session_jobs_session_id
ON mente_session_jobs(session_id, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_mente_session_jobs_session_status
ON mente_session_jobs(session_id, status, updated_at DESC);

CREATE TABLE IF NOT EXISTS mente_task_events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    lane TEXT NOT NULL,
    event_type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_mente_task_events_task_id
ON mente_task_events(task_id, created_at DESC, event_id DESC);

CREATE INDEX IF NOT EXISTS idx_mente_task_events_task_id_event_type
ON mente_task_events(task_id, event_type, created_at DESC, event_id DESC);
"""

_DEFAULT_SESSION_JOB_LANE = "director"


def _normalize_session_job_lane(value: str | None) -> str:
    lane = str(value or "").strip().lower()
    return lane or _DEFAULT_SESSION_JOB_LANE


def _normalize_string_list(values: list[str] | tuple[str, ...] | None) -> list[str]:
    return [str(value).strip() for value in values or [] if str(value).strip()]


def _normalize_json_dict(value: dict[str, object] | None) -> dict[str, object]:
    return dict(value or {})


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

    def bind_session_job(
        self,
        session_id: str,
        *,
        lane: str = _DEFAULT_SESSION_JOB_LANE,
        job_id: str,
        task_id: str,
        status: str,
        summary: str | None = None,
        skill_refs: list[str] | None = None,
        metadata: dict[str, object] | None = None,
    ) -> None:
        """Create or update one active job for a session lane."""

    def get_session_job(
        self,
        session_id: str,
        lane: str = _DEFAULT_SESSION_JOB_LANE,
    ) -> dict[str, object] | None:
        """Return the active job for one session lane."""

    def list_session_jobs(
        self,
        session_id: str,
        status: str | None = None,
    ) -> list[dict[str, object]]:
        """List active jobs for one session."""

    def clear_session_job(
        self,
        session_id: str,
        lane: str = _DEFAULT_SESSION_JOB_LANE,
    ) -> bool:
        """Clear the active job for one session lane."""

    def append_task_event(
        self,
        *,
        task_id: str,
        session_id: str,
        lane: str,
        event_type: str,
        payload: dict[str, object] | None = None,
    ) -> dict[str, object]:
        """Append one event to the task event log."""

    def list_task_events(
        self,
        task_id: str,
        limit: int = 50,
        event_type: str | None = None,
    ) -> list[dict[str, object]]:
        """List task events newest first."""

    def get_latest_task_event(
        self,
        task_id: str,
        event_type: str | None = None,
    ) -> dict[str, object] | None:
        """Return the newest matching task event."""


class InMemoryTaskRepository:
    """Simple in-memory repository for early Mente runtime development."""

    def __init__(self) -> None:
        self._tasks: dict[str, Task] = {}
        self._session_jobs: dict[tuple[str, str], dict[str, object]] = {}
        self._task_events: dict[str, list[dict[str, object]]] = {}
        self._next_event_id = 1

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

    def bind_session_job(
        self,
        session_id: str,
        *,
        lane: str = _DEFAULT_SESSION_JOB_LANE,
        job_id: str,
        task_id: str,
        status: str,
        summary: str | None = None,
        skill_refs: list[str] | None = None,
        metadata: dict[str, object] | None = None,
    ) -> None:
        now = time.time()
        normalized_lane = _normalize_session_job_lane(lane)
        key = (session_id, normalized_lane)
        existing = self._session_jobs.get(key)
        requested_at = (
            float(existing["requested_at"])
            if existing is not None and str(existing.get("job_id") or "") == str(job_id)
            else now
        )
        self._session_jobs[key] = {
            "session_id": session_id,
            "lane": normalized_lane,
            "job_id": str(job_id),
            "task_id": str(task_id),
            "status": str(status or "").strip() or "running",
            "summary": str(summary or "").strip(),
            "requested_at": requested_at,
            "updated_at": now,
            "skill_refs": _normalize_string_list(skill_refs),
            "metadata": _normalize_json_dict(metadata),
        }

    def get_session_job(
        self,
        session_id: str,
        lane: str = _DEFAULT_SESSION_JOB_LANE,
    ) -> dict[str, object] | None:
        payload = self._session_jobs.get((session_id, _normalize_session_job_lane(lane)))
        return dict(payload) if payload is not None else None

    def list_session_jobs(
        self,
        session_id: str,
        status: str | None = None,
    ) -> list[dict[str, object]]:
        normalized_status = str(status or "").strip().lower()
        jobs = [
            dict(payload)
            for (job_session_id, _lane), payload in self._session_jobs.items()
            if job_session_id == session_id
        ]
        if normalized_status:
            jobs = [
                payload
                for payload in jobs
                if str(payload.get("status") or "").strip().lower() == normalized_status
            ]
        jobs.sort(
            key=lambda payload: (
                float(payload.get("updated_at") or 0.0),
                float(payload.get("requested_at") or 0.0),
                str(payload.get("lane") or ""),
            ),
            reverse=True,
        )
        return jobs

    def clear_session_job(
        self,
        session_id: str,
        lane: str = _DEFAULT_SESSION_JOB_LANE,
    ) -> bool:
        key = (session_id, _normalize_session_job_lane(lane))
        if key not in self._session_jobs:
            return False
        self._session_jobs.pop(key, None)
        return True

    def append_task_event(
        self,
        *,
        task_id: str,
        session_id: str,
        lane: str,
        event_type: str,
        payload: dict[str, object] | None = None,
    ) -> dict[str, object]:
        event = {
            "event_id": self._next_event_id,
            "task_id": str(task_id),
            "session_id": str(session_id),
            "lane": _normalize_session_job_lane(lane),
            "event_type": str(event_type or "").strip(),
            "payload": _normalize_json_dict(payload),
            "created_at": time.time(),
        }
        self._next_event_id += 1
        self._task_events.setdefault(str(task_id), []).append(event)
        return dict(event)

    def list_task_events(
        self,
        task_id: str,
        limit: int = 50,
        event_type: str | None = None,
    ) -> list[dict[str, object]]:
        if limit <= 0:
            return []
        normalized_type = str(event_type or "").strip()
        events = [dict(event) for event in self._task_events.get(str(task_id), [])]
        if normalized_type:
            events = [
                event
                for event in events
                if str(event.get("event_type") or "").strip() == normalized_type
            ]
        events.sort(
            key=lambda event: (
                float(event.get("created_at") or 0.0),
                int(event.get("event_id") or 0),
            ),
            reverse=True,
        )
        return events[:limit]

    def get_latest_task_event(
        self,
        task_id: str,
        event_type: str | None = None,
    ) -> dict[str, object] | None:
        events = self.list_task_events(task_id, limit=1, event_type=event_type)
        return events[0] if events else None


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

    def _row_to_session_job(self, row: sqlite3.Row | None) -> dict[str, object] | None:
        if row is None:
            return None
        return {
            "session_id": str(row["session_id"]),
            "lane": str(row["lane"]),
            "job_id": str(row["job_id"]),
            "task_id": str(row["task_id"]),
            "status": str(row["status"]),
            "summary": str(row["summary"]),
            "requested_at": float(row["requested_at"]),
            "updated_at": float(row["updated_at"]),
            "skill_refs": json.loads(row["skill_refs_json"]),
            "metadata": json.loads(row["metadata_json"]),
        }

    def _row_to_task_event(self, row: sqlite3.Row | None) -> dict[str, object] | None:
        if row is None:
            return None
        return {
            "event_id": int(row["event_id"]),
            "task_id": str(row["task_id"]),
            "session_id": str(row["session_id"]),
            "lane": str(row["lane"]),
            "event_type": str(row["event_type"]),
            "payload": json.loads(row["payload_json"]),
            "created_at": float(row["created_at"]),
        }

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

    def bind_session_job(
        self,
        session_id: str,
        *,
        lane: str = _DEFAULT_SESSION_JOB_LANE,
        job_id: str,
        task_id: str,
        status: str,
        summary: str | None = None,
        skill_refs: list[str] | None = None,
        metadata: dict[str, object] | None = None,
    ) -> None:
        now = time.time()
        normalized_lane = _normalize_session_job_lane(lane)
        existing = self._conn.execute(
            """
            SELECT job_id, requested_at
            FROM mente_session_jobs
            WHERE session_id = ? AND lane = ?
            """,
            (session_id, normalized_lane),
        ).fetchone()
        requested_at = (
            float(existing["requested_at"])
            if existing is not None and str(existing["job_id"]) == str(job_id)
            else now
        )
        self._conn.execute(
            """
            INSERT INTO mente_session_jobs (
                session_id,
                lane,
                job_id,
                task_id,
                status,
                summary,
                requested_at,
                updated_at,
                skill_refs_json,
                metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(session_id, lane) DO UPDATE SET
                job_id = excluded.job_id,
                task_id = excluded.task_id,
                status = excluded.status,
                summary = excluded.summary,
                requested_at = excluded.requested_at,
                updated_at = excluded.updated_at,
                skill_refs_json = excluded.skill_refs_json,
                metadata_json = excluded.metadata_json
            """,
            (
                session_id,
                normalized_lane,
                str(job_id),
                str(task_id),
                str(status or "").strip() or "running",
                str(summary or "").strip(),
                requested_at,
                now,
                json.dumps(_normalize_string_list(skill_refs)),
                json.dumps(_normalize_json_dict(metadata), sort_keys=True),
            ),
        )
        self._conn.commit()

    def get_session_job(
        self,
        session_id: str,
        lane: str = _DEFAULT_SESSION_JOB_LANE,
    ) -> dict[str, object] | None:
        row = self._conn.execute(
            """
            SELECT session_id, lane, job_id, task_id, status, summary,
                   requested_at, updated_at, skill_refs_json, metadata_json
            FROM mente_session_jobs
            WHERE session_id = ? AND lane = ?
            """,
            (session_id, _normalize_session_job_lane(lane)),
        ).fetchone()
        return self._row_to_session_job(row)

    def list_session_jobs(
        self,
        session_id: str,
        status: str | None = None,
    ) -> list[dict[str, object]]:
        clauses = ["session_id = ?"]
        params: list[object] = [session_id]
        if status is not None:
            clauses.append("status = ?")
            params.append(str(status))
        rows = self._conn.execute(
            f"""
            SELECT session_id, lane, job_id, task_id, status, summary,
                   requested_at, updated_at, skill_refs_json, metadata_json
            FROM mente_session_jobs
            WHERE {" AND ".join(clauses)}
            ORDER BY updated_at DESC, requested_at DESC, lane DESC
            """,
            params,
        ).fetchall()
        return [self._row_to_session_job(row) for row in rows if row is not None]

    def clear_session_job(
        self,
        session_id: str,
        lane: str = _DEFAULT_SESSION_JOB_LANE,
    ) -> bool:
        cursor = self._conn.execute(
            """
            DELETE FROM mente_session_jobs
            WHERE session_id = ? AND lane = ?
            """,
            (session_id, _normalize_session_job_lane(lane)),
        )
        self._conn.commit()
        return cursor.rowcount > 0

    def append_task_event(
        self,
        *,
        task_id: str,
        session_id: str,
        lane: str,
        event_type: str,
        payload: dict[str, object] | None = None,
    ) -> dict[str, object]:
        cursor = self._conn.execute(
            """
            INSERT INTO mente_task_events (
                task_id,
                session_id,
                lane,
                event_type,
                payload_json,
                created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                str(task_id),
                str(session_id),
                _normalize_session_job_lane(lane),
                str(event_type or "").strip(),
                json.dumps(_normalize_json_dict(payload), sort_keys=True),
                time.time(),
            ),
        )
        self._conn.commit()
        row = self._conn.execute(
            """
            SELECT event_id, task_id, session_id, lane, event_type, payload_json, created_at
            FROM mente_task_events
            WHERE event_id = ?
            """,
            (cursor.lastrowid,),
        ).fetchone()
        event = self._row_to_task_event(row)
        assert event is not None
        return event

    def list_task_events(
        self,
        task_id: str,
        limit: int = 50,
        event_type: str | None = None,
    ) -> list[dict[str, object]]:
        if limit <= 0:
            return []
        clauses = ["task_id = ?"]
        params: list[object] = [str(task_id)]
        if event_type is not None:
            clauses.append("event_type = ?")
            params.append(str(event_type))
        params.append(limit)
        rows = self._conn.execute(
            f"""
            SELECT event_id, task_id, session_id, lane, event_type, payload_json, created_at
            FROM mente_task_events
            WHERE {" AND ".join(clauses)}
            ORDER BY created_at DESC, event_id DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
        return [self._row_to_task_event(row) for row in rows if row is not None]

    def get_latest_task_event(
        self,
        task_id: str,
        event_type: str | None = None,
    ) -> dict[str, object] | None:
        events = self.list_task_events(task_id, limit=1, event_type=event_type)
        return events[0] if events else None

    def close(self) -> None:
        self._conn.close()
