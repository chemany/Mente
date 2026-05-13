from mente.task_core.repository import SQLiteTaskRepository


def test_sqlite_repository_session_jobs_bind_list_supersede_and_clear(
    tmp_path,
    monkeypatch,
):
    db_path = tmp_path / "state.db"
    repo = SQLiteTaskRepository(db_path=db_path)
    timestamps = iter([1000.0, 1001.0, 1002.0])
    monkeypatch.setattr("mente.task_core.repository.time.time", lambda: next(timestamps))

    repo.bind_session_job(
        session_id="session-1",
        lane="research",
        job_id="job-research-1",
        task_id="task-1",
        status="running",
        summary="Collecting sources",
        skill_refs=["skills/research/web"],
        metadata={"task_profile": "research"},
    )
    repo.bind_session_job(
        session_id="session-1",
        lane="engineering",
        job_id="job-engineering-1",
        task_id="task-2",
        status="queued",
        summary="Waiting for worker slot",
        skill_refs=["skills/engineering/debug"],
        metadata={"task_profile": "engineering"},
    )
    repo.bind_session_job(
        session_id="session-1",
        lane="research",
        job_id="job-research-2",
        task_id="task-3",
        status="running",
        summary="Comparing vendors",
        skill_refs=["skills/research/web", "skills/research/compare"],
        metadata={"supersedes_job_id": "job-research-1"},
    )

    research_job = repo.get_session_job("session-1", "research")
    assert research_job is not None
    assert research_job["job_id"] == "job-research-2"
    assert research_job["task_id"] == "task-3"
    assert research_job["summary"] == "Comparing vendors"
    assert research_job["skill_refs"] == [
        "skills/research/web",
        "skills/research/compare",
    ]
    assert research_job["metadata"]["supersedes_job_id"] == "job-research-1"
    assert research_job["requested_at"] == 1002.0
    assert research_job["updated_at"] == 1002.0

    jobs = repo.list_session_jobs("session-1")
    assert [job["lane"] for job in jobs] == ["research", "engineering"]
    assert [job["job_id"] for job in jobs] == [
        "job-research-2",
        "job-engineering-1",
    ]

    running_jobs = repo.list_session_jobs("session-1", status="running")
    assert [job["job_id"] for job in running_jobs] == ["job-research-2"]

    assert repo.clear_session_job("session-1", "research") is True
    assert repo.get_session_job("session-1", "research") is None
    assert [job["job_id"] for job in repo.list_session_jobs("session-1")] == [
        "job-engineering-1"
    ]


def test_sqlite_repository_task_events_persist_and_latest_summary_reads(tmp_path, monkeypatch):
    db_path = tmp_path / "state.db"
    repo = SQLiteTaskRepository(db_path=db_path)
    timestamps = iter([2000.0, 2001.0, 2002.0])
    monkeypatch.setattr("mente.task_core.repository.time.time", lambda: next(timestamps))

    first_event = repo.append_task_event(
        task_id="task-1",
        session_id="session-1",
        lane="research",
        event_type="lane.progress",
        payload={
            "status": "running",
            "headline": "Started research",
            "summary": "Searching official docs",
        },
    )
    second_event = repo.append_task_event(
        task_id="task-1",
        session_id="session-1",
        lane="research",
        event_type="lane.progress",
        payload={
            "status": "running",
            "headline": "Expanded comparison",
            "summary": "Compared two vendors",
        },
    )
    third_event = repo.append_task_event(
        task_id="task-1",
        session_id="session-1",
        lane="research",
        event_type="lane.completed",
        payload={
            "status": "completed",
            "headline": "Finished research",
            "summary": "Delivered final comparison",
        },
    )

    events = repo.list_task_events("task-1")
    assert [event["event_id"] for event in events] == [
        third_event["event_id"],
        second_event["event_id"],
        first_event["event_id"],
    ]
    assert events[0]["payload"]["summary"] == "Delivered final comparison"

    latest_event = repo.get_latest_task_event("task-1")
    assert latest_event is not None
    assert latest_event["event_id"] == third_event["event_id"]
    assert latest_event["payload"]["summary"] == "Delivered final comparison"

    latest_progress_event = repo.get_latest_task_event("task-1", event_type="lane.progress")
    assert latest_progress_event is not None
    assert latest_progress_event["event_id"] == second_event["event_id"]
    assert latest_progress_event["payload"]["summary"] == "Compared two vendors"

    limited = repo.list_task_events("task-1", limit=2)
    assert [event["event_id"] for event in limited] == [
        third_event["event_id"],
        second_event["event_id"],
    ]
