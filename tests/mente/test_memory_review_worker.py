import pytest

from mente.memory.models import MemoryRecord
from mente.memory.repository import InMemoryMemoryRepository
from mente.review.memory_review import MemoryReviewWorker
from mente.task_core.models import Task
from mente.task_core.repository import SQLiteTaskRepository


def _build_task(*, user_request: str, source: str = "gateway") -> Task:
    return Task(
        task_id="task_review_1",
        session_id="session_1",
        task_type="conversation",
        objective="Reply",
        user_request=user_request,
        metadata={
            "source": source,
            "memory_review_artifact": {
                "assistant_summary": "Acknowledged.",
            },
        },
    )


def test_memory_review_worker_skips_when_disabled(monkeypatch, tmp_path):
    task_repo = SQLiteTaskRepository(db_path=tmp_path / "tasks.db")
    memory_repo = InMemoryMemoryRepository()
    task = _build_task(user_request="Remember that I prefer terse replies.")
    task_repo.save(task)
    monkeypatch.setenv("MENTE_MEMORY_REVIEW_ENABLED", "0")

    outcome = MemoryReviewWorker(
        task_repository=task_repo,
        memory_repository=memory_repo,
    ).review_task(task.task_id)

    assert outcome.model_dump(mode="json") == {
        "status": "skipped",
        "reason": "disabled",
        "candidate_count": 0,
        "persisted_count": 0,
        "memory_ids": [],
    }
    stored_task = task_repo.get(task.task_id)
    assert stored_task is not None
    assert stored_task.metadata["memory_review"]["status"] == "skipped"


def test_memory_review_worker_skips_by_default_until_enabled(tmp_path):
    task_repo = SQLiteTaskRepository(db_path=tmp_path / "tasks.db")
    memory_repo = InMemoryMemoryRepository()
    task_repo.save(_build_task(user_request="Remember that I prefer terse replies."))

    outcome = MemoryReviewWorker(
        task_repository=task_repo,
        memory_repository=memory_repo,
    ).review_task("task_review_1")

    assert outcome.model_dump(mode="json") == {
        "status": "skipped",
        "reason": "disabled",
        "candidate_count": 0,
        "persisted_count": 0,
        "memory_ids": [],
    }
    assert memory_repo.list_recent() == []


def test_memory_review_worker_noops_when_no_fact_is_extracted(monkeypatch, tmp_path):
    task_repo = SQLiteTaskRepository(db_path=tmp_path / "tasks.db")
    memory_repo = InMemoryMemoryRepository()
    task = _build_task(user_request="Can you summarize our plan?")
    task_repo.save(task)
    monkeypatch.setenv("MENTE_MEMORY_REVIEW_ENABLED", "1")

    outcome = MemoryReviewWorker(
        task_repository=task_repo,
        memory_repository=memory_repo,
    ).review_task(task.task_id)

    assert outcome.model_dump(mode="json") == {
        "status": "noop",
        "reason": None,
        "candidate_count": 0,
        "persisted_count": 0,
        "memory_ids": [],
    }
    assert memory_repo.list_recent() == []


def test_memory_review_worker_persists_review_memory_from_persisted_task_artifact(
    monkeypatch,
    tmp_path,
):
    task_repo = SQLiteTaskRepository(db_path=tmp_path / "tasks.db")
    memory_repo = InMemoryMemoryRepository()
    task = _build_task(user_request="Remember that I prefer terse replies.")
    task_repo.save(task)
    task.user_request = "Ignore the mutated in-memory copy."
    monkeypatch.setenv("MENTE_MEMORY_REVIEW_ENABLED", "1")

    outcome = MemoryReviewWorker(
        task_repository=task_repo,
        memory_repository=memory_repo,
    ).review_task("task_review_1")

    assert outcome.model_dump(mode="json") == {
        "status": "persisted",
        "reason": None,
        "candidate_count": 1,
        "persisted_count": 1,
        "memory_ids": ["task_review_1:review:0"],
    }
    stored_memory = memory_repo.get("task_review_1:review:0")
    assert stored_memory is not None
    assert stored_memory.fact == "I prefer terse replies."
    assert stored_memory.scope == "session"
    assert stored_memory.session_id == "session_1"
    assert stored_memory.metadata["write_origin"] == "post_turn_memory_review"
    assert stored_memory.metadata["tool_name"] == "mente_memory_review_worker"
    assert stored_memory.metadata["promotion_reason"] == "post_turn_memory_review"


@pytest.mark.parametrize(
    ("user_request", "expected_fact"),
    [
        ("记住我喜欢简洁回答", "我喜欢简洁回答"),
        ("请记住以后先给结论", "以后先给结论"),
        ("帮我记住以后默认给短答案", "以后默认给短答案"),
        ("加入记忆：我更喜欢中文回答", "我更喜欢中文回答"),
        ("记一下我偏好代码示例", "我偏好代码示例"),
        ("你错了，记住以后回答要先说结论", "以后回答要先说结论"),
    ],
    ids=[
        "remember-plain",
        "remember-prefixed-with-please",
        "remember-prefixed-with-help-me",
        "memory-add-command",
        "remember-note-command",
        "criticism-prefix-with-remember-tail",
    ],
)
def test_memory_review_worker_persists_explicit_chinese_remember_intents(
    monkeypatch,
    tmp_path,
    user_request,
    expected_fact,
):
    task_repo = SQLiteTaskRepository(db_path=tmp_path / "tasks.db")
    memory_repo = InMemoryMemoryRepository()
    task_repo.save(_build_task(user_request=user_request))
    monkeypatch.setenv("MENTE_MEMORY_REVIEW_ENABLED", "1")

    outcome = MemoryReviewWorker(
        task_repository=task_repo,
        memory_repository=memory_repo,
    ).review_task("task_review_1")

    assert outcome.model_dump(mode="json") == {
        "status": "persisted",
        "reason": None,
        "candidate_count": 1,
        "persisted_count": 1,
        "memory_ids": ["task_review_1:review:0"],
    }
    stored_memory = memory_repo.get("task_review_1:review:0")
    assert stored_memory is not None
    assert stored_memory.fact == expected_fact
    assert stored_memory.scope == "session"
    assert stored_memory.session_id == "session_1"
    assert stored_memory.metadata["write_origin"] == "post_turn_memory_review"
    assert stored_memory.metadata["tool_name"] == "mente_memory_review_worker"
    assert stored_memory.metadata["promotion_reason"] == "post_turn_memory_review"


@pytest.mark.parametrize(
    ("user_request", "expected_fact"),
    [
        ("我喜欢简洁回答", "我喜欢简洁回答"),
        ("我更喜欢中文回答", "我更喜欢中文回答"),
        ("我偏好先给结论", "我偏好先给结论"),
    ],
    ids=[
        "prefer-like",
        "prefer-like-more",
        "prefer-explicit",
    ],
)
def test_memory_review_worker_persists_explicit_chinese_preference_statements(
    monkeypatch,
    tmp_path,
    user_request,
    expected_fact,
):
    task_repo = SQLiteTaskRepository(db_path=tmp_path / "tasks.db")
    memory_repo = InMemoryMemoryRepository()
    task_repo.save(_build_task(user_request=user_request))
    monkeypatch.setenv("MENTE_MEMORY_REVIEW_ENABLED", "1")

    outcome = MemoryReviewWorker(
        task_repository=task_repo,
        memory_repository=memory_repo,
    ).review_task("task_review_1")

    assert outcome.model_dump(mode="json") == {
        "status": "persisted",
        "reason": None,
        "candidate_count": 1,
        "persisted_count": 1,
        "memory_ids": ["task_review_1:review:0"],
    }
    stored_memory = memory_repo.get("task_review_1:review:0")
    assert stored_memory is not None
    assert stored_memory.fact == expected_fact


@pytest.mark.parametrize(
    "user_request",
    [
        "你错了",
        "这个回答不好",
        "以后注意点",
    ],
    ids=[
        "criticism-wrong",
        "criticism-bad-answer",
        "criticism-vague-future",
    ],
)
def test_memory_review_worker_does_not_persist_pure_criticism_without_remember_cue(
    monkeypatch,
    tmp_path,
    user_request,
):
    task_repo = SQLiteTaskRepository(db_path=tmp_path / "tasks.db")
    memory_repo = InMemoryMemoryRepository()
    task_repo.save(_build_task(user_request=user_request))
    monkeypatch.setenv("MENTE_MEMORY_REVIEW_ENABLED", "1")

    outcome = MemoryReviewWorker(
        task_repository=task_repo,
        memory_repository=memory_repo,
    ).review_task("task_review_1")

    assert outcome.model_dump(mode="json") == {
        "status": "noop",
        "reason": None,
        "candidate_count": 0,
        "persisted_count": 0,
        "memory_ids": [],
    }
    assert memory_repo.list_recent() == []


def test_memory_review_worker_skips_duplicate_fact_already_direct_written(
    monkeypatch,
    tmp_path,
):
    task_repo = SQLiteTaskRepository(db_path=tmp_path / "tasks.db")
    memory_repo = InMemoryMemoryRepository()
    task_repo.save(_build_task(user_request="记住我喜欢简洁回答"))
    memory_repo.save(
        MemoryRecord(
            memory_id="task_review_1:explicit_memory:seed",
            session_id="session_1",
            task_id="task_review_1",
            task_type="conversation",
            source="gateway",
            scope="session",
            fact="我喜欢简洁回答",
            metadata={
                "promotion_reason": "explicit_remember_intent",
                "tool_name": "mente_remember_intent_direct_write",
                "write_origin": "explicit_remember_intent",
                "task_id": "task_review_1",
                "session_id": "session_1",
                "source": "gateway",
                "task_type": "conversation",
            },
        )
    )
    monkeypatch.setenv("MENTE_MEMORY_REVIEW_ENABLED", "1")

    outcome = MemoryReviewWorker(
        task_repository=task_repo,
        memory_repository=memory_repo,
    ).review_task("task_review_1")

    assert outcome.model_dump(mode="json") == {
        "status": "noop",
        "reason": "duplicate_existing",
        "candidate_count": 1,
        "persisted_count": 0,
        "memory_ids": [],
    }
    assert [record.memory_id for record in memory_repo.list_recent()] == [
        "task_review_1:explicit_memory:seed"
    ]


def test_memory_review_worker_exact_match_does_not_depend_on_relevant_limit(
    monkeypatch,
    tmp_path,
):
    task_repo = SQLiteTaskRepository(db_path=tmp_path / "tasks.db")
    memory_repo = InMemoryMemoryRepository()
    task_repo.save(_build_task(user_request="记住我喜欢简洁回答"))
    # Quality contract: exact duplicate detection must be repository-grade,
    # not a bounded relevance scan that misses older active rows.
    memory_repo.save(
        MemoryRecord(
            memory_id="task_review_1:explicit_memory:seed",
            session_id="session_1",
            task_id="task_seed",
            task_type="conversation",
            source="gateway",
            scope="session",
            fact="我喜欢简洁回答",
            created_at=1000.0,
            metadata={
                "promotion_reason": "explicit_remember_intent",
                "tool_name": "mente_remember_intent_direct_write",
                "write_origin": "explicit_remember_intent",
                "task_id": "task_seed",
                "session_id": "session_1",
                "source": "gateway",
                "task_type": "conversation",
            },
        )
    )
    for index in range(60):
        memory_repo.save(
            MemoryRecord(
                memory_id=f"seed_recent_{index}",
                session_id="session_1",
                task_id=f"task_recent_{index}",
                task_type="conversation",
                source="gateway",
                scope="session",
                fact=f"其他偏好 {index}",
                created_at=1100.0 + index,
            )
        )
    monkeypatch.setenv("MENTE_MEMORY_REVIEW_ENABLED", "1")

    outcome = MemoryReviewWorker(
        task_repository=task_repo,
        memory_repository=memory_repo,
    ).review_task("task_review_1")

    assert outcome.model_dump(mode="json") == {
        "status": "noop",
        "reason": "duplicate_existing",
        "candidate_count": 1,
        "persisted_count": 0,
        "memory_ids": [],
    }
    assert [record.fact for record in memory_repo.list_recent(limit=100)] == [
        *(f"其他偏好 {index}" for index in reversed(range(60))),
        "我喜欢简洁回答",
    ]
