from mente.context_builder.builder import ContextBuilder
from mente.memory.models import MemoryRecord
from mente.memory.repository import InMemoryMemoryRepository
from mente.task_core.models import Task


def test_context_builder_produces_execution_request():
    builder = ContextBuilder()
    task = Task(
        task_id="task_1",
        session_id="session_1",
        task_type="engineering",
        objective="Inspect repository",
        user_request="Inspect repository",
    )
    request = builder.build(task)
    assert request.task_id == "task_1"
    assert request.objective == "Inspect repository"


def test_context_builder_prepends_retrieved_memory():
    memory_repo = InMemoryMemoryRepository()
    memory_repo.save(
        MemoryRecord(
            memory_id="mem_1",
            session_id="session_1",
            task_id="task_old",
            task_type="conversation",
            source="gateway",
            scope="session",
            fact="User prefers concise replies.",
        )
    )
    task = Task(
        task_id="task_1",
        session_id="session_1",
        task_type="conversation",
        objective="Reply",
        user_request="Reply",
        memory_facts=["Session context: existing"],
        metadata={"source": "gateway"},
    )
    request = ContextBuilder(memory_repository=memory_repo, memory_limit=5).build(task)
    assert request.memory_facts == [
        "Memory: User prefers concise replies.",
        "Session context: existing",
    ]


def test_context_builder_build_with_trace_reports_selected_and_skipped():
    memory_repo = InMemoryMemoryRepository()
    memory_repo.save(
        MemoryRecord(
            memory_id="mem_1",
            session_id="session_1",
            task_id="task_old_1",
            task_type="conversation",
            source="gateway",
            scope="session",
            fact="User prefers concise replies.",
        )
    )
    memory_repo.save(
        MemoryRecord(
            memory_id="mem_2",
            session_id="session_1",
            task_id="task_old_2",
            task_type="conversation",
            source="gateway",
            scope="session",
            fact="Session context: existing",
        )
    )

    task = Task(
        task_id="task_1",
        session_id="session_1",
        task_type="conversation",
        objective="Reply",
        user_request="Reply",
        memory_facts=["Session context: existing"],
        metadata={"source": "gateway"},
    )

    request, trace = ContextBuilder(
        memory_repository=memory_repo,
        memory_limit=5,
    ).build_with_trace(task)

    assert request.memory_facts == [
        "Memory: User prefers concise replies.",
        "Session context: existing",
    ]
    assert trace.injected_count == 1
    assert [item.memory_id for item in trace.selected] == ["mem_1"]
    assert [(item.memory_id, item.reason) for item in trace.skipped] == [
        ("mem_2", "duplicate_existing_fact"),
    ]


def test_context_builder_applies_policy_scope_and_budget():
    from mente.memory.policy import MemoryPolicy, MemoryPolicyResolver

    repo = InMemoryMemoryRepository()
    repo.save(
        MemoryRecord(
            memory_id="mem_session",
            session_id="session_1",
            task_id="task_old_1",
            task_type="conversation",
            source="gateway",
            scope="session",
            fact="A" * 200,
        )
    )
    repo.save(
        MemoryRecord(
            memory_id="mem_global",
            session_id=None,
            task_id="task_old_2",
            task_type="conversation",
            source="gateway",
            scope="global",
            fact="B" * 200,
        )
    )
    repo.save(
        MemoryRecord(
            memory_id="mem_task_type",
            session_id=None,
            task_id="task_old_3",
            task_type="conversation",
            source="gateway",
            scope="task_type",
            fact="should be filtered",
        )
    )

    policy = MemoryPolicy(
        policy_id="gateway:conversation",
        allowed_injection_scopes=["session", "global"],
        max_injected_memories=2,
        max_chars_per_injected_fact=40,
        max_total_injected_chars=70,
        max_promoted_memories=3,
        max_chars_per_promoted_fact=160,
    )
    resolver = MemoryPolicyResolver(
        profiles={"gateway:conversation": policy, "default": policy},
    )
    task = Task(
        task_id="task_1",
        session_id="session_1",
        task_type="conversation",
        objective="Reply",
        user_request="Reply",
        metadata={"source": "gateway"},
    )

    request, trace = ContextBuilder(
        memory_repository=repo,
        memory_policy_resolver=resolver,
    ).build_with_trace(task)

    assert request.memory_facts == [
        "Memory: " + ("A" * 37) + "...",
    ]
    assert [item.memory_id for item in trace.selected] == ["mem_session"]
    assert [(item.memory_id, item.reason) for item in trace.skipped] == [
        ("mem_global", "prompt_budget_reached"),
        ("mem_task_type", "scope_filtered"),
    ]
    assert trace.prompt_budget_char_count == len(request.memory_facts[0])
    assert trace.policy_id == "gateway:conversation"
