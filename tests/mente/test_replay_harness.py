from pathlib import Path

from mente.context_builder.builder import ContextBuilder
from mente.executors.base import Executor
from mente.memory.repository import InMemoryMemoryRepository
from mente.orchestrator.service import Orchestrator
from mente.task_core.models import ExecutionResult
from mente.task_core.repository import InMemoryTaskRepository
from mente.testing.replay import load_replay_fixture, replay_task


class _FakeExecutor(Executor):
    def execute(self, request):
        return ExecutionResult(status="success", summary=f"ran:{request.task_id}")


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
