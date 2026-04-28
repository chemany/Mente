from mente.context_builder.builder import ContextBuilder
from mente.executors.base import Executor
from mente.memory.models import MemoryRecord
from mente.memory.promoter import MemoryPromoter
from mente.memory.repository import InMemoryMemoryRepository
from mente.orchestrator.service import Orchestrator
from mente.task_core.models import ExecutionResult, Task
from mente.task_core.repository import InMemoryTaskRepository


class _FakeExecutor(Executor):
    def execute(self, request):
        return ExecutionResult(status="success", summary="ok")


class _ExecutorWithMemory(Executor):
    def execute(self, request):
        return ExecutionResult(
            status="success",
            summary="ok",
            memory_candidates=["Repository uses uv for Python commands."],
        )


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


def test_orchestrator_persists_promoted_memory():
    task_repo = InMemoryTaskRepository()
    memory_repo = InMemoryMemoryRepository()
    orchestrator = Orchestrator(
        repository=task_repo,
        context_builder=ContextBuilder(),
        executor=_ExecutorWithMemory(),
        memory_repository=memory_repo,
        memory_promoter=MemoryPromoter(),
    )
    task = Task(
        task_id="task_1",
        session_id="session_1",
        task_type="engineering",
        objective="Inspect repo",
        user_request="Inspect repo",
        metadata={"source": "gateway"},
    )

    result = orchestrator.run(task)

    assert result.status == "success"
    rows = memory_repo.list_relevant(
        session_id="session_1",
        task_type="engineering",
        limit=5,
    )
    assert [row.fact for row in rows] == ["Repository uses uv for Python commands."]
    assert result.metadata["promoted_memory_count"] == 1


def test_orchestrator_persists_memory_context_and_promotion_metadata():
    task_repo = InMemoryTaskRepository()
    memory_repo = InMemoryMemoryRepository()
    memory_repo.save(
        MemoryRecord(
            memory_id="mem_1",
            session_id="session_1",
            task_id="task_old",
            task_type="conversation",
            source="gateway",
            scope="session",
            fact="User prefers concise replies.",
        )
    )
    orchestrator = Orchestrator(
        repository=task_repo,
        context_builder=ContextBuilder(memory_repository=memory_repo),
        executor=_ExecutorWithMemory(),
        memory_repository=memory_repo,
        memory_promoter=MemoryPromoter(),
    )
    task = Task(
        task_id="task_1",
        session_id="session_1",
        task_type="conversation",
        objective="Reply",
        user_request="Reply",
        metadata={"source": "gateway"},
    )

    result = orchestrator.run(task)
    persisted = task_repo.get("task_1")

    assert result.metadata["memory_context"]["injected_count"] == 1
    assert result.metadata["memory_policy"]["policy_id"] == "gateway:conversation"
    assert result.metadata["memory_promotion"]["promoted_count"] == 1
    assert persisted is not None
    assert persisted.metadata["memory_policy"]["policy_id"] == "gateway:conversation"
    assert persisted.metadata["memory_context"]["selected"][0]["memory_id"] == "mem_1"
    assert persisted.metadata["memory_promotion"]["promoted_memory_ids"] == ["task_1:memory:0"]
