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
