from mente.memory.policy import MemoryPolicy, MemoryPolicyResolver
from mente.memory.promoter import MemoryPromoter
from mente.memory.repository import InMemoryMemoryRepository
from mente.task_core.models import ExecutionResult, Task


def test_memory_promoter_deduplicates_candidates():
    promoter = MemoryPromoter()
    task = Task(
        task_id="task_1",
        session_id="session_1",
        task_type="conversation",
        objective="Reply",
        user_request="Reply",
        metadata={"source": "gateway"},
    )
    result = ExecutionResult(
        status="success",
        summary="done",
        memory_candidates=[
            "User prefers concise replies.",
            " User prefers concise replies. ",
            "",
        ],
    )
    promoted = promoter.extract(task, result)
    assert [row.fact for row in promoted] == ["User prefers concise replies."]


def test_memory_promoter_applies_policy_caps_and_truncation():
    policy = MemoryPolicy(
        policy_id="default",
        allowed_injection_scopes=["task_type", "global"],
        max_injected_memories=2,
        max_chars_per_injected_fact=180,
        max_total_injected_chars=360,
        max_promoted_memories=1,
        max_chars_per_promoted_fact=20,
    )
    resolver = MemoryPolicyResolver(profiles={"default": policy})
    promoter = MemoryPromoter(memory_policy_resolver=resolver)
    task = Task(
        task_id="task_1",
        session_id="session_1",
        task_type="engineering",
        objective="Inspect",
        user_request="Inspect",
        metadata={"source": "gateway"},
    )
    result = ExecutionResult(
        status="success",
        summary="done",
        memory_candidates=[
            "This fact is far too long to fit as-is",
            "Second fact should be dropped by max count",
        ],
    )

    promoted = promoter.extract(task, result)

    assert len(promoted) == 1
    assert promoted[0].fact == "This fact is far..."


def test_memory_promoter_uses_session_scope_for_api_server_conversations():
    promoter = MemoryPromoter()
    task = Task(
        task_id="task_1",
        session_id="api-session-1",
        task_type="conversation",
        objective="Reply",
        user_request="Reply",
        metadata={"source": "api_server"},
    )
    result = ExecutionResult(
        status="success",
        summary="done",
        memory_candidates=["User prefers JSON-first replies."],
    )

    promoted = promoter.extract(task, result)

    assert len(promoted) == 1
    assert promoted[0].scope == "session"
    assert promoted[0].session_id == "api-session-1"


def test_memory_promoter_extract_with_trace_records_rejections():
    policy = MemoryPolicy(
        policy_id="default",
        allowed_injection_scopes=["task_type", "global"],
        max_injected_memories=2,
        max_chars_per_injected_fact=180,
        max_total_injected_chars=360,
        max_promoted_memories=1,
        max_chars_per_promoted_fact=40,
    )
    resolver = MemoryPolicyResolver(profiles={"default": policy})
    promoter = MemoryPromoter(memory_policy_resolver=resolver)
    task = Task(
        task_id="task_1",
        session_id="session_1",
        task_type="engineering",
        objective="Inspect",
        user_request="Inspect",
        metadata={"source": "gateway"},
    )
    result = ExecutionResult(
        status="success",
        summary="done",
        memory_candidates=[
            "Use uv for Python commands.",
            "Use uv for Python commands.",
            "Second unique fact should be rejected by cap.",
            "  ",
        ],
    )

    promoted, trace = promoter.extract_with_trace(task, result)

    assert [row.fact for row in promoted] == ["Use uv for Python commands."]
    assert trace.model_dump(mode="json") == {
        "promoted": [
            {
                "fact": "Use uv for Python commands.",
                "reason": "executor_memory_candidate",
                "memory_id": "task_1:memory:0",
                "scope": "task_type",
            }
        ],
        "rejected": [
            {
                "fact": "Use uv for Python commands.",
                "reason": "duplicate_candidate",
                "memory_id": None,
                "scope": None,
            },
            {
                "fact": "Second unique fact should be rejected...",
                "reason": "promotion_limit_reached",
                "memory_id": None,
                "scope": None,
            },
            {
                "fact": "",
                "reason": "empty_candidate",
                "memory_id": None,
                "scope": None,
            },
        ],
    }


def test_memory_promoter_persist_with_trace_uses_atomic_save_seam():
    promoter = MemoryPromoter()
    task = Task(
        task_id="task_1",
        session_id="session_1",
        task_type="conversation",
        objective="Reply",
        user_request="Reply",
        metadata={"source": "gateway"},
    )
    result = ExecutionResult(
        status="success",
        summary="done",
        memory_candidates=["User prefers concise replies."],
    )

    class _AtomicOnlyRepository:
        def __init__(self) -> None:
            self.saved = []

        def save(self, record):
            raise AssertionError("raw save should not be used by memory promoter")

        def save_resolved_fact(self, record):
            self.saved.append(record)
            return record, None

    repository = _AtomicOnlyRepository()

    promoted, trace = promoter.persist_with_trace(task, result, repository)

    assert [record.fact for record in promoted] == ["User prefers concise replies."]
    assert [record.fact for record in repository.saved] == ["User prefers concise replies."]
    assert trace.rejected == []


def test_memory_promoter_persist_with_trace_skips_existing_exact_duplicates():
    promoter = MemoryPromoter()
    repository = InMemoryMemoryRepository()
    repository.save(
        promoter.extract(
            Task(
                task_id="task_seed",
                session_id="session_1",
                task_type="conversation",
                objective="Reply",
                user_request="Reply",
                metadata={"source": "gateway"},
            ),
            ExecutionResult(
                status="success",
                summary="done",
                memory_candidates=["User prefers concise replies."],
            ),
        )[0]
    )
    task = Task(
        task_id="task_1",
        session_id="session_1",
        task_type="conversation",
        objective="Reply",
        user_request="Reply",
        metadata={"source": "gateway"},
    )
    result = ExecutionResult(
        status="success",
        summary="done",
        memory_candidates=["User prefers concise replies."],
    )

    promoted, trace = promoter.persist_with_trace(task, result, repository)

    assert promoted == []
    assert trace.promoted == []
    assert trace.rejected[-1].model_dump(mode="json") == {
        "fact": "User prefers concise replies.",
        "reason": "duplicate_existing",
        "memory_id": "task_seed:memory:0",
        "scope": "session",
    }
    assert len(repository.list_by_session("session_1")) == 1
