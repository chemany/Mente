from mente.memory.models import MemoryRecord


def test_memory_record_defaults():
    record = MemoryRecord(
        memory_id="mem_1",
        task_id="task_1",
        task_type="conversation",
        source="gateway",
        scope="session",
        fact="User prefers concise replies.",
    )
    assert record.kind == "fact"
    assert record.score == 1.0
    assert record.session_id is None
