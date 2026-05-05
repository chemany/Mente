from mente.feature_flags import build_api_server_conversation_workflow_contract
from mente.memory.repository import InMemoryMemoryRepository
from mente.review.session_synthesis import SessionSynthesisWorker
from mente.task_core.models import Task
from mente.task_core.repository import InMemoryTaskRepository


def _build_task(
    task_id: str,
    *,
    contract: dict[str, object],
    assistant_summary: str = "Completed the requested change.",
    follow_up_tasks: list[str] | None = None,
    memory_candidates: list[str] | None = None,
) -> Task:
    return Task(
        task_id=task_id,
        session_id="session-1",
        task_type="conversation",
        objective="Reply",
        user_request=f"request for {task_id}",
        metadata={
            "source": "api_server",
            "workflow_contract": contract,
            "session_synthesis_artifact": {
                "artifact_version": "v1",
                "status": "success",
                "assistant_summary": assistant_summary,
                "actions_taken": [],
                "follow_up_tasks": list(follow_up_tasks or []),
                "memory_candidates": list(memory_candidates or []),
                "promoted_memory_ids": [],
                "requested_execution_mode": "stateless",
                "continuity_status": "stateless",
            },
        },
    )


def _seed_contract(monkeypatch, *, turn_interval: int = 3) -> dict[str, object]:
    monkeypatch.setenv("MENTE_API_SERVER_CONVERSATION_ADOPTION_ENABLED", "1")
    monkeypatch.setenv("MENTE_SESSION_SYNTHESIS_ENABLED", "1")
    monkeypatch.setenv("MENTE_SESSION_SYNTHESIS_TURN_INTERVAL", str(turn_interval))
    return build_api_server_conversation_workflow_contract()


def test_session_synthesis_worker_skips_when_disabled(monkeypatch):
    contract = _seed_contract(monkeypatch)
    monkeypatch.setenv("MENTE_SESSION_SYNTHESIS_ENABLED", "0")

    task_repo = InMemoryTaskRepository()
    memory_repo = InMemoryMemoryRepository()
    task = _build_task("task-1", contract=contract)
    task_repo.save(task)

    outcome = SessionSynthesisWorker(
        task_repository=task_repo,
        memory_repository=memory_repo,
    ).review_task(task.task_id)

    assert outcome.model_dump(mode="json") == {
        "status": "skipped",
        "reason": "disabled",
        "turn_count": 0,
        "turn_interval": 0,
        "window_task_ids": [],
        "memory_id": None,
    }
    stored_task = task_repo.get(task.task_id)
    assert stored_task is not None
    assert stored_task.metadata["session_synthesis"]["status"] == "skipped"
    assert memory_repo.list_recent() == []


def test_session_synthesis_worker_returns_not_due_below_interval(monkeypatch):
    contract = _seed_contract(monkeypatch, turn_interval=3)

    task_repo = InMemoryTaskRepository()
    memory_repo = InMemoryMemoryRepository()
    task_repo.save(_build_task("task-1", contract=contract))
    task_repo.save(_build_task("task-2", contract=contract))

    outcome = SessionSynthesisWorker(
        task_repository=task_repo,
        memory_repository=memory_repo,
    ).review_task("task-2")

    assert outcome.model_dump(mode="json") == {
        "status": "not_due",
        "reason": "insufficient_turns",
        "turn_count": 2,
        "turn_interval": 3,
        "window_task_ids": [],
        "memory_id": "session_summary:api_server:session-1:api_server_conversation",
    }
    assert memory_repo.list_recent() == []


def test_session_synthesis_worker_persists_one_memory_on_cadence_boundary(monkeypatch):
    contract = _seed_contract(monkeypatch, turn_interval=3)

    task_repo = InMemoryTaskRepository()
    memory_repo = InMemoryMemoryRepository()
    task_repo.save(
        _build_task(
            "task-1",
            contract=contract,
            assistant_summary="Captured the rollout constraints.",
            memory_candidates=["Prefer fail-closed rollout."],
        )
    )
    task_repo.save(
        _build_task(
            "task-2",
            contract=contract,
            assistant_summary="Implemented deterministic synthesis scaffolding.",
        )
    )
    task_repo.save(
        _build_task(
            "task-3",
            contract=contract,
            assistant_summary="Finished the bounded worker implementation.",
            follow_up_tasks=["Add bridge helper coverage later."],
        )
    )

    outcome = SessionSynthesisWorker(
        task_repository=task_repo,
        memory_repository=memory_repo,
    ).review_task("task-3")

    memory_id = "session_summary:api_server:session-1:api_server_conversation"
    stored_memory = memory_repo.get(memory_id)

    assert outcome.model_dump(mode="json") == {
        "status": "persisted",
        "reason": None,
        "turn_count": 3,
        "turn_interval": 3,
        "window_task_ids": ["task-1", "task-2", "task-3"],
        "memory_id": memory_id,
    }
    assert stored_memory is not None
    assert stored_memory.memory_id == memory_id
    assert stored_memory.scope == "session"
    assert stored_memory.kind == "session_summary"
    assert stored_memory.score == 2.0
    assert stored_memory.metadata["write_origin"] == "session_synthesis"
    assert stored_memory.metadata["source_task_id"] == "task-3"
    assert stored_memory.metadata["window_task_ids"] == ["task-1", "task-2", "task-3"]
    assert len(memory_repo.list_by_session("session-1")) == 1


def test_session_synthesis_worker_uses_atomic_save_seam(monkeypatch):
    contract = _seed_contract(monkeypatch, turn_interval=1)

    task_repo = InMemoryTaskRepository()
    task_repo.save(
        _build_task(
            "task-1",
            contract=contract,
            assistant_summary="Captured the rollout constraints.",
            memory_candidates=["Prefer fail-closed rollout."],
        )
    )

    class _AtomicOnlyMemoryRepository:
        def __init__(self) -> None:
            self._records = {}

        def save(self, record):
            raise AssertionError("raw save should not be used by session synthesis")

        def save_resolved_fact(self, record):
            self._records[record.memory_id] = record
            return record, None

        def get(self, memory_id: str):
            return self._records.get(memory_id)

        def list_recent(self, *args, **kwargs):
            return list(self._records.values())

        def list_by_session(self, session_id: str, *args, **kwargs):
            return [record for record in self._records.values() if record.session_id == session_id]

    memory_repo = _AtomicOnlyMemoryRepository()

    outcome = SessionSynthesisWorker(
        task_repository=task_repo,
        memory_repository=memory_repo,
    ).review_task("task-1")

    memory_id = "session_summary:api_server:session-1:api_server_conversation"
    stored_memory = memory_repo.get(memory_id)

    assert outcome.status == "persisted"
    assert stored_memory is not None
    assert stored_memory.kind == "session_summary"


def test_session_synthesis_worker_rewrites_same_memory_id_on_later_boundary(monkeypatch):
    contract = _seed_contract(monkeypatch, turn_interval=3)

    task_repo = InMemoryTaskRepository()
    memory_repo = InMemoryMemoryRepository()
    for task_id, summary in (
        ("task-1", "Captured the rollout constraints."),
        ("task-2", "Implemented deterministic synthesis scaffolding."),
        ("task-3", "Finished the bounded worker implementation."),
        ("task-4", "Kept the main reply path unchanged."),
        ("task-5", "Confirmed no bridge helper wiring in this slice."),
        ("task-6", "Prepared worker-only verification."),
    ):
        task_repo.save(
            _build_task(
                task_id,
                contract=contract,
                assistant_summary=summary,
                follow_up_tasks=["Task 3 remains deferred."] if task_id == "task-6" else [],
                memory_candidates=["Prefer worker-only rollout."] if task_id == "task-4" else [],
            )
        )

    worker = SessionSynthesisWorker(
        task_repository=task_repo,
        memory_repository=memory_repo,
    )
    first = worker.review_task("task-3")
    second = worker.review_task("task-6")

    memory_id = "session_summary:api_server:session-1:api_server_conversation"
    stored_memory = memory_repo.get(memory_id)

    assert first.status == "persisted"
    assert second.model_dump(mode="json") == {
        "status": "persisted",
        "reason": None,
        "turn_count": 6,
        "turn_interval": 3,
        "window_task_ids": ["task-4", "task-5", "task-6"],
        "memory_id": memory_id,
    }
    assert stored_memory is not None
    assert stored_memory.task_id == "task-6"
    assert stored_memory.metadata["source_task_id"] == "task-6"
    assert stored_memory.metadata["window_task_ids"] == ["task-4", "task-5", "task-6"]
    assert "Prepared worker-only verification." in stored_memory.fact
    assert len(memory_repo.list_by_session("session-1")) == 1


def test_session_synthesis_worker_refreshes_existing_summary_when_fact_is_identical(monkeypatch):
    contract = _seed_contract(monkeypatch, turn_interval=1)

    task_repo = InMemoryTaskRepository()
    memory_repo = InMemoryMemoryRepository()
    for task_id in ("task-1", "task-2"):
        task_repo.save(
            _build_task(
                task_id,
                contract=contract,
                assistant_summary="Captured the rollout constraints.",
            )
        )

    worker = SessionSynthesisWorker(
        task_repository=task_repo,
        memory_repository=memory_repo,
    )
    first = worker.review_task("task-1")
    second = worker.review_task("task-2")

    memory_id = "session_summary:api_server:session-1:api_server_conversation"
    stored_memory = memory_repo.get(memory_id)

    assert first.status == "persisted"
    assert second.status == "persisted"
    assert stored_memory is not None
    assert stored_memory.task_id == "task-2"
    assert stored_memory.metadata["source_task_id"] == "task-2"
    assert stored_memory.metadata["window_task_ids"] == ["task-2"]
    assert len(memory_repo.list_by_session("session-1")) == 1


def test_session_synthesis_worker_noops_when_window_has_no_useful_signal(monkeypatch):
    contract = _seed_contract(monkeypatch, turn_interval=3)

    task_repo = InMemoryTaskRepository()
    memory_repo = InMemoryMemoryRepository()
    for task_id in ("task-1", "task-2", "task-3"):
        task_repo.save(
            _build_task(
                task_id,
                contract=contract,
                assistant_summary="",
            )
        )

    outcome = SessionSynthesisWorker(
        task_repository=task_repo,
        memory_repository=memory_repo,
    ).review_task("task-3")

    assert outcome.model_dump(mode="json") == {
        "status": "noop",
        "reason": "no_signal",
        "turn_count": 3,
        "turn_interval": 3,
        "window_task_ids": ["task-1", "task-2", "task-3"],
        "memory_id": "session_summary:api_server:session-1:api_server_conversation",
    }
    assert memory_repo.list_recent() == []
