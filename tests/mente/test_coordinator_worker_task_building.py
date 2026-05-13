import threading

from gateway.config import Platform
from gateway.session import SessionSource

from mente.integrations import bridge as mente_bridge
from mente.integrations.bridge import build_gateway_task_bundle, run_gateway_task
from mente.task_core.models import (
    DispatchMode,
    ExecutionMode,
    ExecutionResult,
    ExecutionSession,
    SessionMode,
    TaskRole,
    TaskStatus,
)
from mente.task_core.repository import SQLiteTaskRepository


def _make_source() -> SessionSource:
    return SessionSource(
        platform=Platform.FEISHU,
        chat_id="oc_test",
        chat_name="Feishu",
        chat_type="dm",
        user_id="user-1",
    )


class _FakeUuid:
    def __init__(self, value: str) -> None:
        self.hex = value


def test_build_gateway_task_bundle_creates_explicit_coordinator_and_worker(tmp_path, monkeypatch):
    monkeypatch.setattr("mente.integrations.bridge.uuid.uuid4", lambda: _FakeUuid("bundledeepresearch"))

    bundle = build_gateway_task_bundle(
        message="深度研究一下采用菜籽油制备十三碳二酸的可行性，并输出完整报告",
        context_prompt="session summary",
        history=[],
        source=_make_source(),
        session_id="session-1",
        session_key="agent:main:feishu:dm:oc_test",
        workspace=str(tmp_path),
        execution_mode=ExecutionMode.SESSIONFUL,
        execution_session=ExecutionSession(mode=SessionMode.START),
    )

    coordinator = bundle.coordinator_task
    worker = bundle.worker_task

    assert worker is not None

    assert coordinator.role == TaskRole.COORDINATOR
    assert coordinator.dispatch_mode == DispatchMode.DELEGATE_BACKGROUND
    assert coordinator.parent_task_id is None
    assert coordinator.job_id is not None
    assert coordinator.metadata["worker_task_id"] == worker.task_id
    assert coordinator.metadata["child_task_ids"] == [worker.task_id]
    assert coordinator.metadata["dispatch_decision"]["dispatch_mode"] == "delegate_background"

    assert worker.role == TaskRole.WORKER
    assert worker.parent_task_id == coordinator.task_id
    assert worker.job_id == coordinator.job_id
    assert worker.worker_lane == "research"
    assert worker.skill_refs == ["research/deep-research-pro"]
    assert worker.worker_skill_refs == ["research/deep-research-pro"]
    assert worker.workspace == str(tmp_path)
    assert worker.execution_mode is ExecutionMode.SESSIONFUL
    assert worker.execution_session == ExecutionSession(mode=SessionMode.START)
    assert worker.metadata["lane"] == "research"
    assert worker.metadata["task_profile"] == "deep_research"
    assert any(
        fact.startswith("Deep research workflow brief:")
        for fact in worker.memory_facts
    )


def test_run_gateway_task_executes_worker_and_persists_coordinator_lineage(tmp_path, monkeypatch):
    task_db_path = tmp_path / "state.db"
    memory_db_path = tmp_path / "memory.db"
    monkeypatch.setenv("MENTE_TASK_DB_PATH", str(task_db_path))
    monkeypatch.setenv("MENTE_MEMORY_DB_PATH", str(memory_db_path))
    monkeypatch.setattr("mente.integrations.bridge.uuid.uuid4", lambda: _FakeUuid("runtimeworker"))

    captured = {}

    class _FakeOrchestrator:
        def run(self, task):
            captured["task"] = task
            return ExecutionResult(status="success", summary="worker finished")

    monkeypatch.setattr(
        mente_bridge,
        "_build_orchestrator",
        lambda *args, **kwargs: _FakeOrchestrator(),
    )

    result = run_gateway_task(
        message="深度研究一下采用菜籽油制备十三碳二酸的可行性，并输出完整报告",
        context_prompt="session summary",
        history=[],
        source=_make_source(),
        session_id="session-1",
        session_key="agent:main:feishu:dm:oc_test",
        workspace=str(tmp_path),
        execution_mode=ExecutionMode.SESSIONFUL,
        execution_session=ExecutionSession(mode=SessionMode.START),
        cancel_event=threading.Event(),
    )

    executed_task = captured["task"]
    repository = SQLiteTaskRepository(db_path=task_db_path)
    worker_task = repository.get("mente_gateway_runtimeworker")
    coordinator_task = repository.get("mente_gateway_coordinator_runtimeworker")

    assert result.status == "success"
    assert executed_task.role == TaskRole.WORKER
    assert executed_task.task_id == "mente_gateway_runtimeworker"
    assert executed_task.parent_task_id == "mente_gateway_coordinator_runtimeworker"
    assert executed_task.job_id == coordinator_task.job_id
    assert executed_task.worker_lane == "research"
    assert executed_task.worker_skill_refs == ["research/deep-research-pro"]
    assert executed_task.metadata["task_profile"] == "deep_research"
    assert worker_task is not None
    assert worker_task.role == TaskRole.WORKER
    assert coordinator_task is not None
    assert coordinator_task.role == TaskRole.COORDINATOR
    assert coordinator_task.dispatch_mode == DispatchMode.DELEGATE_BACKGROUND
    assert coordinator_task.metadata["worker_task_id"] == worker_task.task_id
    assert coordinator_task.metadata["child_task_ids"] == [worker_task.task_id]


def test_run_gateway_task_does_not_mark_coordinator_succeeded_before_worker_finishes(
    tmp_path, monkeypatch
):
    task_db_path = tmp_path / "state.db"
    memory_db_path = tmp_path / "memory.db"
    monkeypatch.setenv("MENTE_TASK_DB_PATH", str(task_db_path))
    monkeypatch.setenv("MENTE_MEMORY_DB_PATH", str(memory_db_path))
    monkeypatch.setattr("mente.integrations.bridge.uuid.uuid4", lambda: _FakeUuid("runtimefail"))

    captured = {}

    class _FakeOrchestrator:
        def run(self, task):
            repository = SQLiteTaskRepository(db_path=task_db_path)
            try:
                coordinator = repository.get("mente_gateway_coordinator_runtimefail")
                captured["status_seen_when_worker_starts"] = coordinator.status
            finally:
                repository.close()
            return ExecutionResult(status="error", summary="worker failed", failure_reason="boom")

    monkeypatch.setattr(
        mente_bridge,
        "_build_orchestrator",
        lambda *args, **kwargs: _FakeOrchestrator(),
    )

    result = run_gateway_task(
        message="深度研究一下采用菜籽油制备十三碳二酸的可行性，并输出完整报告",
        context_prompt="session summary",
        history=[],
        source=_make_source(),
        session_id="session-1",
        session_key="agent:main:feishu:dm:oc_test",
        workspace=str(tmp_path),
        execution_mode=ExecutionMode.SESSIONFUL,
        execution_session=ExecutionSession(mode=SessionMode.START),
        cancel_event=threading.Event(),
    )

    repository = SQLiteTaskRepository(db_path=task_db_path)
    coordinator_task = repository.get("mente_gateway_coordinator_runtimefail")
    worker_task = repository.get("mente_gateway_runtimefail")

    assert result.status == "error"
    assert captured["status_seen_when_worker_starts"] != TaskStatus.SUCCEEDED
    assert coordinator_task is not None
    assert coordinator_task.status == TaskStatus.FAILED
    assert coordinator_task.metadata["worker_status"] == "error"
    assert worker_task is not None
    assert worker_task.role == TaskRole.WORKER
