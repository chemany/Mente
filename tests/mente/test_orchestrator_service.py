from mente.context_builder.builder import ContextBuilder
from mente.executors.base import Executor
from mente.orchestrator.service import Orchestrator
from mente.task_core.models import ExecutionResult, Task
from mente.task_core.repository import InMemoryTaskRepository


class _FakeExecutor(Executor):
    def execute(self, request):
        return ExecutionResult(status="success", summary="ok")


def test_orchestrator_runs_task():
    repository = InMemoryTaskRepository()
    orchestrator = Orchestrator(
        repository=repository,
        context_builder=ContextBuilder(),
        executor=_FakeExecutor(),
    )
    task = Task(
        task_id="task_1",
        session_id="session_1",
        task_type="engineering",
        objective="Do work",
        user_request="Do work",
    )
    result = orchestrator.run(task)
    assert result.status == "success"
    stored = repository.get("task_1")
    assert stored is not None
    assert stored.status.value == "succeeded"
