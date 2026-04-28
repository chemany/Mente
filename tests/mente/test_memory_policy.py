from mente.memory.policy import MemoryPolicyResolver
from mente.task_core.models import Task


def test_memory_policy_resolver_prefers_specific_profile():
    resolver = MemoryPolicyResolver.default()
    task = Task(
        task_id="task_1",
        session_id="session_1",
        task_type="conversation",
        objective="Reply",
        user_request="Reply",
        metadata={"source": "gateway"},
    )

    policy = resolver.resolve(task)

    assert policy.policy_id == "gateway:conversation"
    assert policy.max_injected_memories == 3
    assert policy.allowed_injection_scopes == ["session", "global"]
    assert policy.max_total_injected_chars == 480
    assert policy.max_promoted_memories == 3
