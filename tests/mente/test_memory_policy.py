from mente.feature_flags import build_api_server_conversation_workflow_contract
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


def test_memory_policy_resolver_gives_tui_conversation_session_scoped_policy():
    resolver = MemoryPolicyResolver.default()
    task = Task(
        task_id="task_tui_1",
        session_id="session_tui_1",
        task_type="conversation",
        objective="Reply",
        user_request="Reply",
        metadata={"source": "tui"},
    )

    policy = resolver.resolve(task)

    assert policy.policy_id == "tui:conversation"
    assert policy.allowed_injection_scopes == ["session", "global"]
    assert policy.explicit_read_enabled is True
    assert policy.allowed_explicit_read_scopes == ["session", "global"]
    assert policy.explicit_write_enabled is True
    assert policy.allowed_explicit_write_scopes == ["session", "global"]


def test_api_server_adopted_workflow_contract_exposes_session_summary_preload_subcontract():
    contract = build_api_server_conversation_workflow_contract(
        environment={
            "MENTE_API_SERVER_CONVERSATION_ADOPTION_ENABLED": "1",
            "MENTE_SESSION_SUMMARY_RETRIEVAL_ENABLED": "1",
        }
    )

    assert contract["memory_read"] == {
        "mode": "runtime_on_demand_query",
        "enabled": True,
        "session_summary": {
            "enabled": True,
            "scope": "session",
            "kind": "session_summary",
            "priority": "before_generic_memories",
            "max_results": 1,
            "counts_toward_existing_budgets": True,
        },
    }


def test_api_server_workflow_contract_defaults_session_summary_subcontract_fail_closed():
    contract = build_api_server_conversation_workflow_contract(
        environment={
            "MENTE_API_SERVER_CONVERSATION_ADOPTION_ENABLED": "1",
        }
    )

    assert contract["memory_read"] == {
        "mode": "runtime_on_demand_query",
        "enabled": True,
        "session_summary": {
            "enabled": False,
            "scope": "session",
            "kind": "session_summary",
            "priority": "before_generic_memories",
            "max_results": 1,
            "counts_toward_existing_budgets": True,
        },
    }


def test_memory_policy_adopted_api_server_workflow_enables_session_summary_fields():
    resolver = MemoryPolicyResolver.default()
    task = Task(
        task_id="task_1",
        session_id="session_1",
        task_type="conversation",
        objective="Reply",
        user_request="Reply",
        metadata={
            "source": "api_server",
            "workflow_contract": build_api_server_conversation_workflow_contract(
                environment={
                    "MENTE_API_SERVER_CONVERSATION_ADOPTION_ENABLED": "1",
                    "MENTE_SESSION_SUMMARY_RETRIEVAL_ENABLED": "1",
                }
            ),
        },
    )

    policy = resolver.resolve(task)

    assert policy.policy_id == "api_server:conversation"
    assert policy.session_summary_retrieval_enabled is True
    assert policy.session_summary_scope == "session"
    assert policy.session_summary_kind == "session_summary"
    assert policy.max_session_summary_results == 1
    assert policy.max_chars_per_session_summary == 160


def test_memory_policy_non_adopted_gateway_task_remains_unchanged():
    resolver = MemoryPolicyResolver.default()
    task = Task(
        task_id="task_2",
        session_id="session_2",
        task_type="conversation",
        objective="Reply",
        user_request="Reply",
        metadata={"source": "gateway"},
    )

    policy = resolver.resolve(task)

    assert policy.model_dump() == {
        "policy_id": "gateway:conversation",
        "allowed_injection_scopes": ["session", "global"],
        "max_injected_memories": 3,
        "max_chars_per_injected_fact": 160,
        "max_total_injected_chars": 480,
        "max_promoted_memories": 3,
        "max_chars_per_promoted_fact": 160,
        "explicit_read_enabled": True,
        "allowed_explicit_read_scopes": ["session", "global"],
        "max_explicit_read_results": 3,
        "max_chars_per_explicit_read_fact": 160,
        "explicit_write_enabled": True,
        "allowed_explicit_write_scopes": ["session", "global"],
        "max_chars_per_explicit_write_fact": 160,
        "session_summary_retrieval_enabled": False,
        "session_summary_scope": None,
        "session_summary_kind": None,
        "max_session_summary_results": 0,
        "max_chars_per_session_summary": 0,
    }


def test_memory_policy_non_adopted_tui_task_matches_gateway_conversation_shape():
    resolver = MemoryPolicyResolver.default()
    task = Task(
        task_id="task_tui_2",
        session_id="session_tui_2",
        task_type="conversation",
        objective="Reply",
        user_request="Reply",
        metadata={"source": "tui"},
    )

    policy = resolver.resolve(task)

    assert policy.model_dump() == {
        "policy_id": "tui:conversation",
        "allowed_injection_scopes": ["session", "global"],
        "max_injected_memories": 3,
        "max_chars_per_injected_fact": 160,
        "max_total_injected_chars": 480,
        "max_promoted_memories": 3,
        "max_chars_per_promoted_fact": 160,
        "explicit_read_enabled": True,
        "allowed_explicit_read_scopes": ["session", "global"],
        "max_explicit_read_results": 3,
        "max_chars_per_explicit_read_fact": 160,
        "explicit_write_enabled": True,
        "allowed_explicit_write_scopes": ["session", "global"],
        "max_chars_per_explicit_write_fact": 160,
        "session_summary_retrieval_enabled": False,
        "session_summary_scope": None,
        "session_summary_kind": None,
        "max_session_summary_results": 0,
        "max_chars_per_session_summary": 0,
    }
