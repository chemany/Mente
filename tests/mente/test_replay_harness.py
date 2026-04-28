from pathlib import Path

from mente.context_builder.builder import ContextBuilder
from mente.executors.base import Executor
from mente.memory.repository import InMemoryMemoryRepository
from mente.orchestrator.service import Orchestrator
from mente.task_core.models import ExecutionResult
from mente.task_core.repository import InMemoryTaskRepository
from mente.testing.replay import compare_memory_replay, load_replay_fixture, replay_task


class _FakeExecutor(Executor):
    def execute(self, request):
        return ExecutionResult(status="success", summary=f"ran:{request.task_id}")


class _RecordingExecutor(Executor):
    def __init__(self):
        self.requests = []

    def execute(self, request):
        self.requests.append(request)
        return ExecutionResult(status="success", summary=request.objective)


def test_replay_task_runs_normalized_fixture():
    result = replay_task(
        fixture={
            "task": {
                "task_id": "task_1",
                "session_id": "session_1",
                "task_type": "conversation",
                "objective": "Reply",
                "user_request": "Reply",
            }
        },
        orchestrator=Orchestrator(
            repository=InMemoryTaskRepository(),
            context_builder=ContextBuilder(memory_repository=InMemoryMemoryRepository()),
            executor=_FakeExecutor(),
        ),
    )
    assert result.summary == "ran:task_1"


def test_gateway_fixture_replays():
    fixture = load_replay_fixture(Path("tests/mente/fixtures/replay/gateway_conversation.json"))
    result = replay_task(
        fixture,
        Orchestrator(
            repository=InMemoryTaskRepository(),
            context_builder=ContextBuilder(memory_repository=InMemoryMemoryRepository()),
            executor=_FakeExecutor(),
        ),
    )
    assert result.status == "success"


def test_cron_fixture_replays():
    fixture = load_replay_fixture(Path("tests/mente/fixtures/replay/cron_job.json"))
    result = replay_task(
        fixture,
        Orchestrator(
            repository=InMemoryTaskRepository(),
            context_builder=ContextBuilder(memory_repository=InMemoryMemoryRepository()),
            executor=_FakeExecutor(),
        ),
    )
    assert result.status == "success"


def test_compare_memory_replay_reports_injected_memory():
    fixture = {
        "seed_memories": [
            {
                "memory_id": "mem_1",
                "session_id": "session_1",
                "task_id": "task_old",
                "task_type": "conversation",
                "source": "gateway",
                "scope": "session",
                "fact": "User prefers concise replies.",
            }
        ],
        "task": {
            "task_id": "task_1",
            "session_id": "session_1",
            "task_type": "conversation",
            "objective": "Reply",
            "user_request": "Reply",
            "metadata": {"source": "gateway"},
        },
    }

    comparison = compare_memory_replay(
        fixture,
        executor_factory=_RecordingExecutor,
    )

    assert comparison["baseline"]["memory_fact_count"] == 0
    assert comparison["memory_enabled"]["memory_fact_count"] == 1
    assert comparison["memory_enabled"]["selected_memory_ids"] == ["mem_1"]
