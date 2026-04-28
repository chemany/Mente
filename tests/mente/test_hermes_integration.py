from gateway.config import Platform
from gateway.session import SessionSource

from mente.integrations.hermes import (
    build_cron_task,
    build_gateway_task,
    run_cron_task,
    run_gateway_task,
)
from mente.task_core.models import ExecutionResult
from mente.task_core.repository import SQLiteTaskRepository


def test_build_cron_task_normalizes_job_into_task(tmp_path):
    task = build_cron_task(
        job={
            "id": "job-1",
            "name": "Nightly Sync",
            "schedule": "0 2 * * *",
            "schedule_display": "daily at 02:00",
            "deliver": "telegram",
        },
        prompt="sync the repo",
        session_id="cron_job-1_20260428",
        workspace=str(tmp_path),
    )

    assert task.task_type == "cron"
    assert task.session_id == "cron_job-1_20260428"
    assert task.user_request == "sync the repo"
    assert task.workspace == str(tmp_path)
    assert task.metadata["source"] == "cron"
    assert "Cron job ID: job-1" in task.constraints


def test_build_gateway_task_normalizes_context_and_history(tmp_path):
    source = SessionSource(
        platform=Platform.LOCAL,
        chat_id="cli",
        chat_name="CLI",
        chat_type="dm",
        user_id="user-1",
    )

    task = build_gateway_task(
        message="latest question",
        context_prompt="session summary",
        history=[
            {
                "role": "user",
                "content": "previous question",
                "timestamp": "2026-04-28T12:00:00Z",
            }
        ],
        source=source,
        session_id="session-1",
        session_key="agent:main:local:dm",
        channel_prompt="be concise",
        workspace=str(tmp_path),
    )

    assert task.task_type == "conversation"
    assert task.session_id == "session-1"
    assert task.user_request == "latest question"
    assert task.workspace == str(tmp_path)
    assert task.metadata["source"] == "gateway"
    assert task.metadata["platform"] == "local"
    assert any("Session context:" in fact for fact in task.memory_facts)
    assert any("Channel prompt:" in fact for fact in task.memory_facts)
    history_fact = next(
        fact for fact in task.memory_facts if fact.startswith("Conversation history (JSON):")
    )
    assert '"role":"user"' in history_fact
    assert "timestamp" not in history_fact


def test_run_cron_task_persists_task_record(tmp_path, monkeypatch):
    db_path = tmp_path / "state.db"
    monkeypatch.setenv("MENTE_TASK_DB_PATH", str(db_path))

    class _FakeUuid:
        hex = "cronfixed"

    monkeypatch.setattr("mente.integrations.hermes.uuid.uuid4", lambda: _FakeUuid())
    monkeypatch.setattr(
        "mente.integrations.hermes.CodexExecutor.execute",
        lambda self, request: ExecutionResult(status="success", summary="done"),
    )

    result = run_cron_task(
        job={"id": "job-1", "name": "Nightly Sync"},
        prompt="sync the repo",
        session_id="cron_job-1_20260428",
        workspace=str(tmp_path),
    )

    stored = SQLiteTaskRepository(db_path=db_path).get("mente_cron_job-1_cronfixed")
    assert result.status == "success"
    assert stored is not None
    assert stored.metadata["source"] == "cron"
    assert stored.status.value == "succeeded"


def test_run_gateway_task_persists_task_record(tmp_path, monkeypatch):
    db_path = tmp_path / "state.db"
    monkeypatch.setenv("MENTE_TASK_DB_PATH", str(db_path))

    class _FakeUuid:
        hex = "gatewayfixed"

    monkeypatch.setattr("mente.integrations.hermes.uuid.uuid4", lambda: _FakeUuid())
    monkeypatch.setattr(
        "mente.integrations.hermes.CodexExecutor.execute",
        lambda self, request: ExecutionResult(status="success", summary="done"),
    )
    source = SessionSource(
        platform=Platform.LOCAL,
        chat_id="cli",
        chat_name="CLI",
        chat_type="dm",
        user_id="user-1",
    )

    result = run_gateway_task(
        message="latest question",
        context_prompt="session summary",
        history=[],
        source=source,
        session_id="session-1",
        session_key="agent:main:local:dm",
        channel_prompt="be concise",
        workspace=str(tmp_path),
    )

    stored = SQLiteTaskRepository(db_path=db_path).get("mente_gateway_gatewayfixed")
    assert result.status == "success"
    assert stored is not None
    assert stored.metadata["source"] == "gateway"
    assert stored.status.value == "succeeded"


def test_run_cron_task_closes_repository(monkeypatch, tmp_path):
    class _FakeRepo:
        def __init__(self):
            self.closed = False

        def save(self, task):
            return None

        def get(self, task_id):
            return None

        def close(self):
            self.closed = True

    fake_repo = _FakeRepo()
    monkeypatch.setattr(
        "mente.integrations.hermes.SQLiteTaskRepository",
        lambda: fake_repo,
    )
    monkeypatch.setattr(
        "mente.integrations.hermes.CodexExecutor.execute",
        lambda self, request: ExecutionResult(status="success", summary="done"),
    )

    run_cron_task(
        job={"id": "job-1", "name": "Nightly Sync"},
        prompt="sync the repo",
        session_id="cron_job-1_20260428",
        workspace=str(tmp_path),
    )

    assert fake_repo.closed is True


def test_run_gateway_task_closes_repository(monkeypatch, tmp_path):
    class _FakeRepo:
        def __init__(self):
            self.closed = False

        def save(self, task):
            return None

        def get(self, task_id):
            return None

        def close(self):
            self.closed = True

    fake_repo = _FakeRepo()
    monkeypatch.setattr(
        "mente.integrations.hermes.SQLiteTaskRepository",
        lambda: fake_repo,
    )
    monkeypatch.setattr(
        "mente.integrations.hermes.CodexExecutor.execute",
        lambda self, request: ExecutionResult(status="success", summary="done"),
    )
    source = SessionSource(
        platform=Platform.LOCAL,
        chat_id="cli",
        chat_name="CLI",
        chat_type="dm",
        user_id="user-1",
    )

    run_gateway_task(
        message="latest question",
        context_prompt="session summary",
        history=[],
        source=source,
        session_id="session-1",
        session_key="agent:main:local:dm",
        channel_prompt="be concise",
        workspace=str(tmp_path),
    )

    assert fake_repo.closed is True
