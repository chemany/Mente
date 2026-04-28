from mente.memory.policy import MemoryPolicy, MemoryPolicyResolver
from mente.memory.promoter import MemoryPromoter
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
