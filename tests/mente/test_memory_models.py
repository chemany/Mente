from mente.memory.models import MemoryBuildTrace, MemoryRecord, MemoryTraceItem


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


def test_memory_trace_models_serialize_deterministically():
    trace = MemoryBuildTrace(
        retrieved_count=2,
        injected_count=1,
        selected=[
            MemoryTraceItem(
                memory_id="mem_1",
                scope="session",
                fact="User prefers concise replies.",
                reason="scope_match",
            )
        ],
        skipped=[
            MemoryTraceItem(
                memory_id="mem_2",
                scope="session",
                fact="Session context: existing",
                reason="duplicate_existing_fact",
            )
        ],
    )

    assert trace.model_dump(mode="json") == {
        "retrieved_count": 2,
        "injected_count": 1,
        "selected": [
            {
                "memory_id": "mem_1",
                "scope": "session",
                "fact": "User prefers concise replies.",
                "reason": "scope_match",
            }
        ],
        "skipped": [
            {
                "memory_id": "mem_2",
                "scope": "session",
                "fact": "Session context: existing",
                "reason": "duplicate_existing_fact",
            }
        ],
    }
