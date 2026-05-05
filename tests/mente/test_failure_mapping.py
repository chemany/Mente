import subprocess

from mente.context_builder.builder import ContextBuilder
from mente.executors.base import Executor
from mente.executors.codex import CodexExecutor
from mente.orchestrator.service import Orchestrator
from mente.task_core.models import ExecutionRequest, ExecutionResult, Task
from mente.task_core.repository import InMemoryTaskRepository


def test_codex_executor_maps_spawn_failure(monkeypatch):
    executor = CodexExecutor(codex_binary="missing-codex")
    request = ExecutionRequest(
        task_id="task_1",
        session_id="session_1",
        task_type="engineering",
        objective="Inspect repository",
        user_request="inspect repository",
        workspace=".",
    )

    def _raise(*args, **kwargs):
        raise FileNotFoundError("missing-codex")

    monkeypatch.setattr(subprocess, "run", _raise)
    result = executor.execute(request)
    assert result.status == "failed"
    assert result.failure_reason == "runtime_not_bootstrapped:missing-codex"


class _FailingExecutor(Executor):
    def execute(self, request):
        return ExecutionResult(
            status="failed",
            summary="failed",
            failure_reason="exit_code:1",
        )


def test_orchestrator_persists_failed_status():
    repository = InMemoryTaskRepository()
    orchestrator = Orchestrator(
        repository=repository,
        context_builder=ContextBuilder(),
        executor=_FailingExecutor(),
    )
    task = Task(
        task_id="task_1",
        session_id="session_1",
        task_type="engineering",
        objective="Do work",
        user_request="Do work",
    )
    result = orchestrator.run(task)
    assert result.failure_reason == "exit_code:1"
    stored = repository.get("task_1")
    assert stored is not None
    assert stored.status.value == "failed"
