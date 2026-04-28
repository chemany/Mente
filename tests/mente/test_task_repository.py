from mente.task_core.models import Task, TaskStatus
from mente.task_core.repository import InMemoryTaskRepository, SQLiteTaskRepository


def test_repository_round_trip():
    repo = InMemoryTaskRepository()
    task = Task(
        task_id="task_1",
        session_id="session_1",
        task_type="engineering",
        objective="Do work",
        user_request="Do work",
    )
    repo.save(task)
    loaded = repo.get("task_1")
    assert loaded is not None
    assert loaded.task_id == "task_1"


def test_sqlite_repository_round_trip_persists_across_instances(tmp_path):
    db_path = tmp_path / "state.db"
    task = Task(
        task_id="task_sqlite_1",
        session_id="session_1",
        task_type="engineering",
        objective="Do work",
        user_request="Do work",
    )

    SQLiteTaskRepository(db_path=db_path).save(task)

    loaded = SQLiteTaskRepository(db_path=db_path).get("task_sqlite_1")
    assert loaded is not None
    assert loaded.task_id == "task_sqlite_1"
    assert loaded.status == TaskStatus.INGESTED


def test_sqlite_repository_updates_existing_task(tmp_path):
    db_path = tmp_path / "state.db"
    repo = SQLiteTaskRepository(db_path=db_path)
    task = Task(
        task_id="task_sqlite_2",
        session_id="session_2",
        task_type="engineering",
        objective="Do work",
        user_request="Do work",
    )
    repo.save(task)

    task.status = TaskStatus.SUCCEEDED
    repo.save(task)

    loaded = SQLiteTaskRepository(db_path=db_path).get("task_sqlite_2")
    assert loaded is not None
    assert loaded.status == TaskStatus.SUCCEEDED


def test_sqlite_repository_list_by_session_returns_newest_first(tmp_path, monkeypatch):
    db_path = tmp_path / "state.db"
    repo = SQLiteTaskRepository(db_path=db_path)
    timestamps = iter([1000.0, 1001.0, 1002.0])
    monkeypatch.setattr("mente.task_core.repository.time.time", lambda: next(timestamps))

    repo.save(
        Task(
            task_id="task_sqlite_session_old",
            session_id="session-1",
            task_type="engineering",
            objective="Older task",
            user_request="Older task",
        )
    )
    repo.save(
        Task(
            task_id="task_sqlite_other_session",
            session_id="session-2",
            task_type="engineering",
            objective="Other session task",
            user_request="Other session task",
        )
    )
    repo.save(
        Task(
            task_id="task_sqlite_session_new",
            session_id="session-1",
            task_type="engineering",
            objective="Newer task",
            user_request="Newer task",
        )
    )

    tasks = repo.list_by_session("session-1")

    assert [task.task_id for task in tasks] == [
        "task_sqlite_session_new",
        "task_sqlite_session_old",
    ]


def test_sqlite_repository_list_recent_filters_and_limits(tmp_path, monkeypatch):
    db_path = tmp_path / "state.db"
    repo = SQLiteTaskRepository(db_path=db_path)
    timestamps = iter([2000.0, 2001.0, 2002.0])
    monkeypatch.setattr("mente.task_core.repository.time.time", lambda: next(timestamps))

    repo.save(
        Task(
            task_id="task_sqlite_recent_1",
            session_id="session-1",
            task_type="engineering",
            objective="Gateway first",
            user_request="Gateway first",
            metadata={"source": "gateway"},
        )
    )
    repo.save(
        Task(
            task_id="task_sqlite_recent_2",
            session_id="session-2",
            task_type="engineering",
            objective="Gateway second",
            user_request="Gateway second",
            metadata={"source": "gateway"},
        )
    )
    repo.save(
        Task(
            task_id="task_sqlite_recent_3",
            session_id="session-3",
            task_type="engineering",
            objective="Cron task",
            user_request="Cron task",
            metadata={"source": "cron"},
        )
    )

    recent = repo.list_recent(limit=2)
    gateway_recent = repo.list_recent(limit=1, source="gateway")

    assert [task.task_id for task in recent] == [
        "task_sqlite_recent_3",
        "task_sqlite_recent_2",
    ]
    assert [task.task_id for task in gateway_recent] == ["task_sqlite_recent_2"]


def test_sqlite_repository_list_recent_supports_offset(tmp_path, monkeypatch):
    db_path = tmp_path / "state.db"
    repo = SQLiteTaskRepository(db_path=db_path)
    timestamps = iter([2500.0, 2501.0, 2502.0, 2503.0])
    monkeypatch.setattr("mente.task_core.repository.time.time", lambda: next(timestamps))

    for idx in range(4):
        repo.save(
            Task(
                task_id=f"task_sqlite_recent_offset_{idx}",
                session_id=f"session-{idx}",
                task_type="conversation",
                objective=f"Task {idx}",
                user_request=f"Task {idx}",
                metadata={"source": "gateway"},
            )
        )

    tasks = repo.list_recent(limit=2, offset=1)

    assert [task.task_id for task in tasks] == [
        "task_sqlite_recent_offset_2",
        "task_sqlite_recent_offset_1",
    ]


def test_sqlite_repository_list_by_session_filters_status_and_task_type(tmp_path, monkeypatch):
    db_path = tmp_path / "state.db"
    repo = SQLiteTaskRepository(db_path=db_path)
    timestamps = iter([3000.0, 3001.0, 3002.0])
    monkeypatch.setattr("mente.task_core.repository.time.time", lambda: next(timestamps))

    repo.save(
        Task(
            task_id="task_sqlite_session_filter_1",
            session_id="session-filter",
            task_type="conversation",
            objective="Executing conversation",
            user_request="Executing conversation",
            status=TaskStatus.EXECUTING,
            metadata={"source": "gateway"},
        )
    )
    repo.save(
        Task(
            task_id="task_sqlite_session_filter_2",
            session_id="session-filter",
            task_type="cron",
            objective="Succeeded cron",
            user_request="Succeeded cron",
            status=TaskStatus.SUCCEEDED,
            metadata={"source": "cron"},
        )
    )
    repo.save(
        Task(
            task_id="task_sqlite_session_filter_3",
            session_id="session-filter",
            task_type="conversation",
            objective="Succeeded conversation",
            user_request="Succeeded conversation",
            status=TaskStatus.SUCCEEDED,
            metadata={"source": "gateway"},
        )
    )

    tasks = repo.list_by_session(
        "session-filter",
        status=TaskStatus.SUCCEEDED.value,
        task_type="conversation",
    )

    assert [task.task_id for task in tasks] == ["task_sqlite_session_filter_3"]


def test_sqlite_repository_list_by_session_supports_offset(tmp_path, monkeypatch):
    db_path = tmp_path / "state.db"
    repo = SQLiteTaskRepository(db_path=db_path)
    timestamps = iter([3500.0, 3501.0, 3502.0])
    monkeypatch.setattr("mente.task_core.repository.time.time", lambda: next(timestamps))

    for idx in range(3):
        repo.save(
            Task(
                task_id=f"task_sqlite_session_offset_{idx}",
                session_id="session-offset",
                task_type="conversation",
                objective=f"Task {idx}",
                user_request=f"Task {idx}",
                metadata={"source": "gateway"},
            )
        )

    tasks = repo.list_by_session("session-offset", limit=1, offset=1)

    assert [task.task_id for task in tasks] == ["task_sqlite_session_offset_1"]


def test_sqlite_repository_list_recent_filters_status_source_and_task_type(tmp_path, monkeypatch):
    db_path = tmp_path / "state.db"
    repo = SQLiteTaskRepository(db_path=db_path)
    timestamps = iter([4000.0, 4001.0, 4002.0, 4003.0])
    monkeypatch.setattr("mente.task_core.repository.time.time", lambda: next(timestamps))

    repo.save(
        Task(
            task_id="task_sqlite_recent_filter_1",
            session_id="session-1",
            task_type="conversation",
            objective="Gateway succeeded",
            user_request="Gateway succeeded",
            status=TaskStatus.SUCCEEDED,
            metadata={"source": "gateway"},
        )
    )
    repo.save(
        Task(
            task_id="task_sqlite_recent_filter_2",
            session_id="session-2",
            task_type="cron",
            objective="Cron executing",
            user_request="Cron executing",
            status=TaskStatus.EXECUTING,
            metadata={"source": "cron"},
        )
    )
    repo.save(
        Task(
            task_id="task_sqlite_recent_filter_3",
            session_id="session-3",
            task_type="cron",
            objective="Cron succeeded",
            user_request="Cron succeeded",
            status=TaskStatus.SUCCEEDED,
            metadata={"source": "cron"},
        )
    )
    repo.save(
        Task(
            task_id="task_sqlite_recent_filter_4",
            session_id="session-4",
            task_type="cron",
            objective="Cron failed",
            user_request="Cron failed",
            status=TaskStatus.FAILED,
            metadata={"source": "cron"},
        )
    )

    tasks = repo.list_recent(
        limit=2,
        source="cron",
        status=TaskStatus.SUCCEEDED.value,
        task_type="cron",
    )

    assert [task.task_id for task in tasks] == ["task_sqlite_recent_filter_3"]
