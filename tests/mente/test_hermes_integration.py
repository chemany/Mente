from gateway.config import Platform
from gateway.session import SessionSource

from mente.integrations import hermes as hermes_bridge
from mente.executors import CodexKernelAdapter
from mente.integrations.hermes import (
    build_api_server_task,
    build_cron_task,
    build_gateway_task,
    run_api_server_task,
    run_cron_task,
    run_gateway_task,
)
from mente.memory.repository import SQLiteMemoryRepository
from mente.task_core.models import ExecutionResult
from mente.task_core.repository import SQLiteTaskRepository


class _FakeKernelAdapter(CodexKernelAdapter):
    def __init__(self, result: ExecutionResult | None = None) -> None:
        self.result = result or ExecutionResult(status="success", summary="done")

    def build_request_payload(self, request) -> dict[str, object]:
        return {
            "prompt": request.user_request,
            "workspace": request.workspace,
        }

    def execute(self, request) -> ExecutionResult:
        return self.result


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


def test_build_api_server_task_sets_api_server_source(tmp_path):
    task = build_api_server_task(
        user_message="Remember this preference",
        conversation_history=[
            {
                "role": "assistant",
                "content": "Prior reply",
                "timestamp": "2026-04-29T12:00:00Z",
            }
        ],
        session_id="api-session-1",
        api_mode="chat_completions",
        workspace=str(tmp_path),
    )

    assert task.session_id == "api-session-1"
    assert task.task_type == "conversation"
    assert task.workspace == str(tmp_path)
    assert task.metadata["source"] == "api_server"
    assert task.metadata["api_mode"] == "chat_completions"
    history_fact = next(
        fact for fact in task.memory_facts if fact.startswith("Conversation history (JSON):")
    )
    assert '"role":"assistant"' in history_fact
    assert "timestamp" not in history_fact


def test_build_orchestrator_includes_memory_stack(monkeypatch):
    captured = {}

    class _FakeOrchestrator:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(hermes_bridge, "Orchestrator", _FakeOrchestrator)

    hermes_bridge._build_orchestrator(".", repository=object())

    assert captured["memory_repository"] is not None
    assert captured["memory_promoter"] is not None
    assert captured["context_builder"] is not None


def test_build_orchestrator_uses_kernel_adapter_factory(monkeypatch):
    captured = {}
    fake_adapter = _FakeKernelAdapter()

    class _FakeOrchestrator:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(hermes_bridge, "Orchestrator", _FakeOrchestrator)
    monkeypatch.setattr(hermes_bridge, "_build_kernel_adapter", lambda: fake_adapter)

    hermes_bridge._build_orchestrator(".", repository=object())

    assert captured["executor"] is fake_adapter


def test_api_server_isolation_executor_preserves_kernel_adapter_contract():
    request = build_api_server_task(
        user_message="latest question",
        conversation_history=[],
        session_id="api-session-1",
        api_mode="responses",
        workspace=".",
    )
    inner = _FakeKernelAdapter(
        result=ExecutionResult(
            status="success",
            summary="done",
            memory_candidates=["User previously said they prefer terse replies."],
        )
    )

    executor = hermes_bridge._APIServerIsolationExecutor(inner=inner)

    payload = executor.build_request_payload(request)
    result = executor.execute(request)

    assert payload == {
        "prompt": request.user_request,
        "workspace": request.workspace,
    }
    assert executor.supports_kernel_sessions() is False
    assert result.summary == "done"
    assert result.memory_candidates == []


def test_second_run_receives_first_run_memory(monkeypatch, tmp_path):
    task_db_path = tmp_path / "tasks.db"
    memory_db_path = tmp_path / "memory.db"
    monkeypatch.setenv("MENTE_TASK_DB_PATH", str(task_db_path))
    monkeypatch.setenv("MENTE_MEMORY_DB_PATH", str(memory_db_path))

    seen_requests = []

    def _fake_execute(self, request):
        seen_requests.append(request)
        if len(seen_requests) == 1:
            return ExecutionResult(
                status="success",
                summary="first",
                memory_candidates=["User prefers concise replies."],
            )
        return ExecutionResult(status="success", summary="second")

    monkeypatch.setattr("mente.integrations.hermes.CodexExecutor.execute", _fake_execute)

    source = SessionSource(
        platform=Platform.LOCAL,
        chat_id="cli",
        chat_name="CLI",
        chat_type="dm",
        user_id="user-1",
    )

    run_gateway_task(
        message="first question",
        context_prompt="session summary",
        history=[],
        source=source,
        session_id="session-1",
        session_key="agent:main:local:dm",
        channel_prompt="be concise",
        workspace=str(tmp_path),
    )
    run_gateway_task(
        message="second question",
        context_prompt="session summary",
        history=[],
        source=source,
        session_id="session-1",
        session_key="agent:main:local:dm",
        channel_prompt="be concise",
        workspace=str(tmp_path),
    )

    assert len(seen_requests) == 2
    assert "Memory: User prefers concise replies." in seen_requests[1].memory_facts


def test_gateway_runs_persist_memory_observability_metadata(monkeypatch, tmp_path):
    task_db_path = tmp_path / "tasks.db"
    memory_db_path = tmp_path / "memory.db"
    monkeypatch.setenv("MENTE_TASK_DB_PATH", str(task_db_path))
    monkeypatch.setenv("MENTE_MEMORY_DB_PATH", str(memory_db_path))

    class _FakeUuid:
        def __init__(self, value):
            self.hex = value

    uuids = iter((_FakeUuid("gatewayfirst"), _FakeUuid("gatewaysecond")))
    monkeypatch.setattr("mente.integrations.hermes.uuid.uuid4", lambda: next(uuids))

    def _fake_execute(self, request):
        if request.task_id.endswith("gatewayfirst"):
            return ExecutionResult(
                status="success",
                summary="first",
                memory_candidates=["User prefers concise replies."],
            )
        return ExecutionResult(status="success", summary="second")

    monkeypatch.setattr("mente.integrations.hermes.CodexExecutor.execute", _fake_execute)

    source = SessionSource(
        platform=Platform.LOCAL,
        chat_id="cli",
        chat_name="CLI",
        chat_type="dm",
        user_id="user-1",
    )

    first_result = run_gateway_task(
        message="first question",
        context_prompt="session summary",
        history=[],
        source=source,
        session_id="session-1",
        session_key="agent:main:local:dm",
        channel_prompt="be concise",
        workspace=str(tmp_path),
    )
    second_result = run_gateway_task(
        message="second question",
        context_prompt="session summary",
        history=[],
        source=source,
        session_id="session-1",
        session_key="agent:main:local:dm",
        channel_prompt="be concise",
        workspace=str(tmp_path),
    )

    repository = SQLiteTaskRepository(db_path=task_db_path)
    second_task = repository.get("mente_gateway_gatewaysecond")

    assert first_result.metadata["memory_promotion"]["promoted_memory_ids"] == [
        "mente_gateway_gatewayfirst:memory:0"
    ]
    assert second_result.metadata["memory_policy"]["policy_id"] == "gateway:conversation"
    assert second_result.metadata["memory_context"]["injected_count"] == 1
    assert second_task is not None
    assert second_task.metadata["memory_policy"]["policy_id"] == "gateway:conversation"
    assert second_task.metadata["memory_context"]["selected"][0]["memory_id"] == (
        "mente_gateway_gatewayfirst:memory:0"
    )


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


def test_run_api_server_task_persists_task_record(tmp_path, monkeypatch):
    db_path = tmp_path / "state.db"
    monkeypatch.setenv("MENTE_TASK_DB_PATH", str(db_path))

    class _FakeUuid:
        hex = "apifixed"

    monkeypatch.setattr("mente.integrations.hermes.uuid.uuid4", lambda: _FakeUuid())
    monkeypatch.setattr(
        "mente.integrations.hermes.CodexExecutor.execute",
        lambda self, request: ExecutionResult(
            status="success",
            summary="done",
            memory_candidates=["User prefers JSON-first replies."],
        ),
    )

    result = run_api_server_task(
        user_message="latest question",
        conversation_history=[{"role": "assistant", "content": "Prior reply"}],
        session_id="api-session-1",
        api_mode="responses",
        workspace=str(tmp_path),
    )

    stored = SQLiteTaskRepository(db_path=db_path).get("mente_api_server_apifixed")
    assert result.status == "success"
    assert stored is not None
    assert stored.metadata["source"] == "api_server"
    assert stored.metadata["api_mode"] == "responses"
    assert stored.status.value == "succeeded"


def test_api_server_second_run_selects_session_memory(tmp_path, monkeypatch):
    task_db_path = tmp_path / "tasks.db"
    memory_db_path = tmp_path / "memory.db"
    monkeypatch.setenv("MENTE_TASK_DB_PATH", str(task_db_path))
    monkeypatch.setenv("MENTE_MEMORY_DB_PATH", str(memory_db_path))

    class _FakeUuid:
        def __init__(self, value):
            self.hex = value

    uuids = iter((_FakeUuid("apifirst"), _FakeUuid("apisecond")))
    monkeypatch.setattr("mente.integrations.hermes.uuid.uuid4", lambda: next(uuids))

    def _fake_execute(self, request):
        if request.task_id.endswith("apifirst"):
            return ExecutionResult(
                status="success",
                summary="first",
                memory_candidates=["User prefers JSON-first replies."],
            )
        return ExecutionResult(status="success", summary="second")

    monkeypatch.setattr("mente.integrations.hermes.CodexExecutor.execute", _fake_execute)

    first_result = run_api_server_task(
        user_message="Remember this preference",
        conversation_history=[],
        session_id="api-session-1",
        api_mode="chat_completions",
        workspace=str(tmp_path),
    )
    second_result = run_api_server_task(
        user_message="What do I prefer?",
        conversation_history=[],
        session_id="api-session-1",
        api_mode="chat_completions",
        workspace=str(tmp_path),
    )

    stored_memory = SQLiteMemoryRepository(db_path=memory_db_path).get(
        "mente_api_server_apifirst:memory:0"
    )
    stored_task = SQLiteTaskRepository(db_path=task_db_path).get("mente_api_server_apisecond")

    assert first_result.metadata["memory_promotion"]["promoted_memory_ids"] == [
        "mente_api_server_apifirst:memory:0"
    ]
    assert stored_memory is not None
    assert stored_memory.scope == "session"
    assert stored_memory.session_id == "api-session-1"
    assert second_result.metadata["memory_context"]["selected"][0]["memory_id"] == (
        "mente_api_server_apifirst:memory:0"
    )
    assert stored_task is not None
    assert stored_task.metadata["memory_context"]["selected"][0]["memory_id"] == (
        "mente_api_server_apifirst:memory:0"
    )


def test_api_server_fresh_session_does_not_promote_fabricated_prior_preferences(tmp_path, monkeypatch):
    task_db_path = tmp_path / "tasks.db"
    memory_db_path = tmp_path / "memory.db"
    monkeypatch.setenv("MENTE_TASK_DB_PATH", str(task_db_path))
    monkeypatch.setenv("MENTE_MEMORY_DB_PATH", str(memory_db_path))

    class _FakeUuid:
        hex = "apiisolated"

    monkeypatch.setattr("mente.integrations.hermes.uuid.uuid4", lambda: _FakeUuid())
    monkeypatch.setattr(
        "mente.integrations.hermes.CodexExecutor.execute",
        lambda self, request: ExecutionResult(
            status="success",
            summary="You mentioned earlier that you prefer terse replies.",
            memory_candidates=["User previously said they prefer terse replies."],
        ),
    )

    result = run_api_server_task(
        user_message="What preferences did I mention earlier?",
        conversation_history=[],
        session_id="api-session-empty",
        api_mode="chat_completions",
        workspace=str(tmp_path),
    )

    stored_task = SQLiteTaskRepository(db_path=task_db_path).get("mente_api_server_apiisolated")
    session_memories = SQLiteMemoryRepository(db_path=memory_db_path).list_by_session(
        "api-session-empty",
        source="api_server",
        task_type="conversation",
        memory_scope="session",
    )

    assert result.metadata["memory_context"]["selected"] == []
    assert result.metadata["memory_promotion"]["promoted_memory_ids"] == []
    assert stored_task is not None
    assert stored_task.metadata["memory_context"]["selected"] == []
    assert stored_task.metadata["memory_promotion"]["promoted_memory_ids"] == []
    assert session_memories == []


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
