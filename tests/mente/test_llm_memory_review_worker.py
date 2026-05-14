import pytest

from mente.feature_flags import build_conversation_workflow_contract
from mente.memory.models import MemoryRecord
from mente.memory.repository import InMemoryMemoryRepository
from mente.review.llm_memory_review import LLMMemoryReviewWorker
from mente.task_core.models import Task
from mente.task_core.repository import InMemoryTaskRepository


def _build_task(*, artifact: dict[str, object] | None = None) -> Task:
    return Task(
        task_id="task_llm_review_1",
        session_id="session_1",
        task_type="conversation",
        objective="Reply",
        user_request="请以后发布小红书时直接走脚本，不要走 MCP。",
        metadata={
            "source": "gateway",
            "workflow_contract": build_conversation_workflow_contract(source="gateway"),
            "llm_memory_review_artifact": artifact
            or {
                "assistant_summary": "Acknowledged that future Rednote publishing should use the CLI script.",
                "status": "success",
                "actions_taken": ["Confirmed user preference."],
                "commands_run": ["rednote publish --draft article.md"],
                "tool_calls": [],
                "artifacts_out": ["article.md"],
                "follow_up_tasks": [],
            },
        },
    )


def test_llm_memory_review_worker_persists_medium_confidence_facts(monkeypatch):
    monkeypatch.setenv("MENTE_LLM_MEMORY_REVIEW_ENABLED", "1")
    task_repo = InMemoryTaskRepository()
    memory_repo = InMemoryMemoryRepository()
    task = _build_task()
    task_repo.save(task)

    def _fake_call_llm(**kwargs):
        prompt = kwargs["messages"][1]["content"]
        assert "rednote publish --draft article.md" in prompt

        class _Message:
            content = (
                '{"should_write": true, "facts": ["发布小红书内容时直接调用 rednote CLI 脚本,不走 MCP"], '
                '"confidence": "medium", "reason": "stable user preference"}'
            )

        class _Choice:
            message = _Message()

        class _Response:
            choices = [_Choice()]

        return _Response()

    monkeypatch.setattr("mente.review.llm_memory_review.call_llm", _fake_call_llm)

    outcome = LLMMemoryReviewWorker(
        task_repository=task_repo,
        memory_repository=memory_repo,
    ).review_task(task.task_id)

    assert outcome.model_dump(mode="json") == {
        "status": "persisted",
        "reason": "stable user preference",
        "candidate_count": 1,
        "persisted_count": 1,
        "memory_ids": ["task_llm_review_1:llm_review:0"],
        "confidence": "medium",
    }
    stored_memory = memory_repo.get("task_llm_review_1:llm_review:0")
    assert stored_memory is not None
    assert stored_memory.fact == "发布小红书内容时直接调用 rednote CLI 脚本,不走 MCP"
    assert stored_memory.scope == "session"
    assert stored_memory.metadata["write_origin"] == "post_turn_llm_memory_review"
    assert stored_memory.metadata["tool_name"] == "mente_llm_memory_review_worker"
    assert stored_memory.metadata["promotion_reason"] == "post_turn_llm_memory_review"


@pytest.mark.parametrize(
    "payload",
    [
        '{"should_write": false, "facts": ["不要写"], "confidence": "high", "reason": "task only"}',
        '{"should_write": true, "facts": ["低置信事实"], "confidence": "low", "reason": "weak"}',
    ],
)
def test_llm_memory_review_worker_noops_when_model_declines_or_confidence_is_low(
    monkeypatch,
    payload,
):
    monkeypatch.setenv("MENTE_LLM_MEMORY_REVIEW_ENABLED", "1")
    task_repo = InMemoryTaskRepository()
    memory_repo = InMemoryMemoryRepository()
    task = _build_task()
    task_repo.save(task)

    def _fake_call_llm(**kwargs):
        class _Message:
            content = payload

        class _Choice:
            message = _Message()

        class _Response:
            choices = [_Choice()]

        return _Response()

    monkeypatch.setattr("mente.review.llm_memory_review.call_llm", _fake_call_llm)

    outcome = LLMMemoryReviewWorker(
        task_repository=task_repo,
        memory_repository=memory_repo,
    ).review_task(task.task_id)

    assert outcome.status == "noop"
    assert outcome.persisted_count == 0
    assert memory_repo.list_recent() == []


def test_llm_memory_review_worker_deduplicates_existing_fact(monkeypatch):
    monkeypatch.setenv("MENTE_LLM_MEMORY_REVIEW_ENABLED", "1")
    task_repo = InMemoryTaskRepository()
    memory_repo = InMemoryMemoryRepository()
    task = _build_task()
    task_repo.save(task)
    memory_repo.save(
        MemoryRecord(
            memory_id="seed",
            session_id="session_1",
            task_id="seed_task",
            task_type="conversation",
            source="gateway",
            scope="session",
            fact="发布小红书内容时直接调用 rednote CLI 脚本,不走 MCP",
        )
    )

    def _fake_call_llm(**kwargs):
        class _Message:
            content = (
                '{"should_write": true, "facts": ["发布小红书内容时直接调用 rednote CLI 脚本，不走 MCP"], '
                '"confidence": "high", "reason": "stable user preference"}'
            )

        class _Choice:
            message = _Message()

        class _Response:
            choices = [_Choice()]

        return _Response()

    monkeypatch.setattr("mente.review.llm_memory_review.call_llm", _fake_call_llm)

    outcome = LLMMemoryReviewWorker(
        task_repository=task_repo,
        memory_repository=memory_repo,
    ).review_task(task.task_id)

    assert outcome.status == "noop"
    assert outcome.reason == "duplicate_existing"
    assert outcome.candidate_count == 1
    assert outcome.persisted_count == 0
    assert [record.memory_id for record in memory_repo.list_recent()] == ["seed"]


def test_llm_memory_review_worker_respects_env_disabled_and_does_not_call_model(monkeypatch):
    monkeypatch.setenv("MENTE_LLM_MEMORY_REVIEW_ENABLED", "0")
    task_repo = InMemoryTaskRepository()
    memory_repo = InMemoryMemoryRepository()
    task = _build_task()
    task_repo.save(task)

    def _fail_call_llm(**kwargs):
        raise AssertionError("disabled LLM memory review must not call the model")

    monkeypatch.setattr("mente.review.llm_memory_review.call_llm", _fail_call_llm)

    outcome = LLMMemoryReviewWorker(
        task_repository=task_repo,
        memory_repository=memory_repo,
    ).review_task(task.task_id)

    assert outcome.status == "skipped"
    assert outcome.reason == "disabled"
    assert memory_repo.list_recent() == []


def test_llm_memory_review_worker_skips_missing_artifact(monkeypatch):
    monkeypatch.setenv("MENTE_LLM_MEMORY_REVIEW_ENABLED", "1")
    task_repo = InMemoryTaskRepository()
    memory_repo = InMemoryMemoryRepository()
    task = _build_task(artifact={})
    task.metadata.pop("llm_memory_review_artifact")
    task_repo.save(task)

    outcome = LLMMemoryReviewWorker(
        task_repository=task_repo,
        memory_repository=memory_repo,
    ).review_task(task.task_id)

    assert outcome.status == "skipped"
    assert outcome.reason == "missing_artifact"
    assert memory_repo.list_recent() == []


def test_llm_memory_review_worker_filters_sensitive_facts(monkeypatch):
    monkeypatch.setenv("MENTE_LLM_MEMORY_REVIEW_ENABLED", "1")
    task_repo = InMemoryTaskRepository()
    memory_repo = InMemoryMemoryRepository()
    task = _build_task()
    task_repo.save(task)

    def _fake_call_llm(**kwargs):
        class _Message:
            content = (
                '{"should_write": true, "facts": ["用户 API key 是 sk-secret", '
                '"发布小红书内容时直接调用 rednote CLI 脚本,不走 MCP"], '
                '"confidence": "high", "reason": "stable preference"}'
            )

        class _Choice:
            message = _Message()

        class _Response:
            choices = [_Choice()]

        return _Response()

    monkeypatch.setattr("mente.review.llm_memory_review.call_llm", _fake_call_llm)

    outcome = LLMMemoryReviewWorker(
        task_repository=task_repo,
        memory_repository=memory_repo,
    ).review_task(task.task_id)

    memories = memory_repo.list_recent()
    assert outcome.status == "persisted"
    assert outcome.candidate_count == 1
    assert len(memories) == 1
    assert memories[0].fact == "发布小红书内容时直接调用 rednote CLI 脚本,不走 MCP"
