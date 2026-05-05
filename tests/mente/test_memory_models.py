from mente.memory.models import (
    MemoryAuditPayload,
    MemoryBuildTrace,
    MemoryPromotionTrace,
    MemoryPromotionTraceItem,
    MemoryRecord,
    MemoryTraceItem,
)


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
        policy_id="gateway:conversation",
        prompt_budget_char_count=39,
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
        "policy_id": "gateway:conversation",
        "prompt_budget_char_count": 39,
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


def test_memory_audit_payload_serializes_deterministically():
    audit = MemoryAuditPayload(
        policy_id="gateway:conversation",
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
                scope="global",
                fact="Use Markdown bullets.",
                reason="duplicate_existing_fact",
            )
        ],
        promoted=[
            MemoryPromotionTraceItem(
                memory_id="task_1:memory:0",
                scope="session",
                fact="User prefers concise replies.",
                reason="executor_memory_candidate",
            )
        ],
        rejected=[
            MemoryPromotionTraceItem(
                fact="User prefers concise replies.",
                reason="duplicate_candidate",
            )
        ],
    )

    assert audit.model_dump(mode="json") == {
        "policy_id": "gateway:conversation",
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
                "scope": "global",
                "fact": "Use Markdown bullets.",
                "reason": "duplicate_existing_fact",
            }
        ],
        "promoted": [
            {
                "memory_id": "task_1:memory:0",
                "scope": "session",
                "fact": "User prefers concise replies.",
                "reason": "executor_memory_candidate",
            }
        ],
        "rejected": [
            {
                "fact": "User prefers concise replies.",
                "reason": "duplicate_candidate",
                "memory_id": None,
                "scope": None,
            }
        ],
    }


def test_memory_promotion_trace_defaults_to_low_noise_lists():
    trace = MemoryPromotionTrace()

    assert trace.model_dump(mode="json") == {
        "promoted": [],
        "rejected": [],
    }
