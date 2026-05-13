from gateway.config import GatewayConfig
from gateway.session import SessionStore


def test_session_store_session_jobs_round_trip_reload_and_clear(tmp_path):
    first = SessionStore(sessions_dir=tmp_path, config=GatewayConfig())
    first._db = None

    first.bind_session_job(
        "sess-1",
        lane="research",
        job_id="job-research-1",
        task_id="task-1",
        status="running",
        summary="Collecting sources",
        skill_refs=["skills/research/web"],
        metadata={"task_profile": "research"},
    )
    first.bind_session_job(
        "sess-1",
        lane="engineering",
        job_id="job-engineering-1",
        task_id="task-2",
        status="queued",
        summary="Waiting for worker slot",
        skill_refs=["skills/engineering/debug"],
        metadata={"task_profile": "engineering"},
    )
    first.bind_session_job(
        "sess-1",
        lane="research",
        job_id="job-research-2",
        task_id="task-3",
        status="running",
        summary="Comparing vendors",
        skill_refs=["skills/research/web", "skills/research/compare"],
        metadata={"supersedes_job_id": "job-research-1"},
    )

    research_job = first.get_session_job("sess-1", "research")
    assert research_job is not None
    assert research_job["job_id"] == "job-research-2"
    assert research_job["task_id"] == "task-3"
    assert research_job["summary"] == "Comparing vendors"
    assert research_job["skill_refs"] == [
        "skills/research/web",
        "skills/research/compare",
    ]
    assert research_job["metadata"]["supersedes_job_id"] == "job-research-1"
    assert research_job["lane"] == "research"
    assert research_job["requested_at"]
    assert research_job["updated_at"]

    jobs = first.list_session_jobs("sess-1")
    assert [job["lane"] for job in jobs] == ["research", "engineering"]
    assert [job["job_id"] for job in jobs] == [
        "job-research-2",
        "job-engineering-1",
    ]

    second = SessionStore(sessions_dir=tmp_path, config=GatewayConfig())
    second._db = None

    reloaded = second.get_session_job("sess-1", "research")
    assert reloaded is not None
    assert reloaded["job_id"] == "job-research-2"
    assert reloaded["metadata"]["supersedes_job_id"] == "job-research-1"

    running_jobs = second.list_session_jobs("sess-1", status="running")
    assert [job["job_id"] for job in running_jobs] == ["job-research-2"]

    assert second.clear_session_job("sess-1", "research") is True
    assert second.get_session_job("sess-1", "research") is None
    assert [job["job_id"] for job in second.list_session_jobs("sess-1")] == [
        "job-engineering-1"
    ]
