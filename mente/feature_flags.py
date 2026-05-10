"""Minimal operator-facing feature flags for staged Mente rollouts."""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from typing import Any


_FALSE_VALUES = {"0", "false", "off", "no"}
API_SERVER_CONVERSATION_WORKFLOW_ID = "api_server_conversation"
API_SERVER_CONVERSATION_ADOPTION_ID = "api_server_conversation_memory_and_skill_v1"
_BRIDGE_TOOL_FLAGS = {
    "mente_memory_query": "MENTE_MEMORY_READ_TOOL_ENABLED",
    "mente_memory_save": "MENTE_MEMORY_WRITE_TOOL_ENABLED",
}
_BRIDGE_TOOL_FLAG_DEFAULTS = {
    "mente_memory_query": True,
    "mente_memory_save": False,
}


def is_env_flag_enabled(
    name: str,
    *,
    default: bool = False,
    environment: Mapping[str, str] | None = None,
) -> bool:
    """Return the normalized boolean value for one operator-facing env flag."""

    env = environment or os.environ
    raw_value = env.get(name)
    if raw_value is None:
        return default
    return raw_value.strip().lower() not in _FALSE_VALUES


def filter_enabled_bridge_tools(
    tool_names: Sequence[str],
    *,
    environment: Mapping[str, str] | None = None,
) -> list[str]:
    """Filter bridge tools by their operator-facing rollout flags."""

    enabled_tools: list[str] = []
    for tool_name in tool_names:
        flag_name = _BRIDGE_TOOL_FLAGS.get(tool_name)
        if flag_name is not None and not is_env_flag_enabled(
            flag_name,
            default=_BRIDGE_TOOL_FLAG_DEFAULTS.get(tool_name, False),
            environment=environment,
        ):
            continue
        enabled_tools.append(tool_name)
    return enabled_tools


def is_memory_read_tool_enabled(
    *,
    environment: Mapping[str, str] | None = None,
) -> bool:
    """Return whether explicit memory reads are enabled for operator rollout."""

    return is_env_flag_enabled(
        "MENTE_MEMORY_READ_TOOL_ENABLED",
        default=True,
        environment=environment,
    )


def is_memory_write_tool_enabled(
    *,
    environment: Mapping[str, str] | None = None,
) -> bool:
    """Return whether explicit memory writes are enabled for operator rollout."""

    return is_env_flag_enabled(
        "MENTE_MEMORY_WRITE_TOOL_ENABLED",
        default=False,
        environment=environment,
    )


def is_memory_review_enabled(
    *,
    environment: Mapping[str, str] | None = None,
) -> bool:
    """Return whether post-turn memory review is enabled for operator rollout."""

    return is_env_flag_enabled(
        "MENTE_MEMORY_REVIEW_ENABLED",
        default=False,
        environment=environment,
    )


def is_remember_intent_direct_write_enabled(
    *,
    environment: Mapping[str, str] | None = None,
) -> bool:
    """Return whether explicit remember-intent direct-write is enabled."""

    return is_env_flag_enabled(
        "MENTE_REMEMBER_INTENT_DIRECT_WRITE_ENABLED",
        default=False,
        environment=environment,
    )


def is_skill_review_enabled(
    *,
    environment: Mapping[str, str] | None = None,
) -> bool:
    """Return whether post-turn skill review is enabled for operator rollout."""

    return is_env_flag_enabled(
        "MENTE_SKILL_REVIEW_ENABLED",
        default=False,
        environment=environment,
    )


def is_session_synthesis_enabled(
    *,
    environment: Mapping[str, str] | None = None,
) -> bool:
    """Return whether post-turn session synthesis is enabled for rollout."""

    return is_env_flag_enabled(
        "MENTE_SESSION_SYNTHESIS_ENABLED",
        default=False,
        environment=environment,
    )


def is_session_summary_retrieval_enabled(
    *,
    environment: Mapping[str, str] | None = None,
) -> bool:
    """Return whether explicit session-summary retrieval is enabled for rollout."""

    return is_env_flag_enabled(
        "MENTE_SESSION_SUMMARY_RETRIEVAL_ENABLED",
        default=False,
        environment=environment,
    )


def is_sessionful_execution_enabled(
    *,
    environment: Mapping[str, str] | None = None,
) -> bool:
    """Return whether bounded sessionful execution is enabled for rollout."""

    return is_env_flag_enabled(
        "MENTE_SESSIONFUL_EXECUTION_ENABLED",
        default=False,
        environment=environment,
    )


def is_gateway_runtime_continuity_enabled(
    *,
    environment: Mapping[str, str] | None = None,
) -> bool:
    """Return whether gateway runtime continuity should be requested."""

    return is_sessionful_execution_enabled(
        environment=environment,
    ) and is_env_flag_enabled(
        "MENTE_GATEWAY_CONTINUITY_ENABLED",
        default=False,
        environment=environment,
    )


def gateway_runtime_continuity_idle_ttl_seconds(
    *,
    environment: Mapping[str, str] | None = None,
) -> float | None:
    """Return the maximum idle age for one gateway continuity binding.

    ``None`` disables idle-age invalidation.
    """

    env = environment or os.environ
    raw = env.get("MENTE_GATEWAY_CONTINUITY_IDLE_TTL_SECONDS")
    if raw is None:
        return 4 * 60 * 60
    text = str(raw).strip()
    if not text:
        return 4 * 60 * 60
    try:
        value = float(text)
    except ValueError:
        return 4 * 60 * 60
    if value <= 0:
        return None
    return value


def is_api_server_conversation_adoption_enabled(
    *,
    environment: Mapping[str, str] | None = None,
) -> bool:
    """Return whether the first api_server conversation adoption slice is enabled."""

    return is_env_flag_enabled(
        "MENTE_API_SERVER_CONVERSATION_ADOPTION_ENABLED",
        default=False,
        environment=environment,
    )


def sessionful_execution_sources(
    *,
    environment: Mapping[str, str] | None = None,
) -> set[str]:
    """Return the bounded source allowlist for sessionful execution."""

    return parse_allowed_sources(
        "MENTE_SESSIONFUL_EXECUTION_SOURCES",
        default_sources=("api_server", "gateway", "tui", "oneshot"),
        environment=environment,
    )


def session_synthesis_sources(
    *,
    environment: Mapping[str, str] | None = None,
) -> set[str]:
    """Return the bounded source allowlist for session synthesis."""

    return parse_allowed_sources(
        "MENTE_SESSION_SYNTHESIS_SOURCES",
        default_sources=("api_server", "gateway", "tui", "oneshot"),
        environment=environment,
    )


def session_synthesis_turn_interval(
    *,
    environment: Mapping[str, str] | None = None,
) -> int:
    """Return the operator-configured synthesis cadence, defaulting safely."""

    env = environment or os.environ
    raw_value = str(env.get("MENTE_SESSION_SYNTHESIS_TURN_INTERVAL") or "").strip()
    if not raw_value:
        return 5
    try:
        interval = int(raw_value)
    except ValueError:
        return 5
    return interval if interval > 0 else 5


def build_conversation_workflow_contract(
    *,
    source: str,
    skill_refs: Sequence[str] | None = None,
    execution_mode: str = "stateless",
    environment: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Build the machine-readable rollout contract for one conversation entrypoint."""

    normalized_source = str(source).strip() or "unknown"
    normalized_skill_refs = [
        str(item).strip()
        for item in (skill_refs or [])
        if str(item).strip()
    ]
    if normalized_source == "api_server":
        adoption_enabled = is_api_server_conversation_adoption_enabled(environment=environment)
        workflow_id = API_SERVER_CONVERSATION_WORKFLOW_ID
        adoption_id = API_SERVER_CONVERSATION_ADOPTION_ID
    else:
        adoption_enabled = True
        workflow_id = f"{normalized_source}_conversation"
        adoption_id = f"{normalized_source}_conversation_memory_and_skill_v1"

    session_summary_enabled = adoption_enabled and is_session_summary_retrieval_enabled(
        environment=environment
    )
    session_synthesis_enabled = (
        adoption_enabled
        and is_session_synthesis_enabled(environment=environment)
        and normalized_source in session_synthesis_sources(environment=environment)
    )
    review_enabled = normalized_source == "api_server" and adoption_enabled

    return {
        "workflow_id": workflow_id,
        "adoption_id": adoption_id,
        "source": normalized_source,
        "task_type": "conversation",
        "adoption_enabled": adoption_enabled,
        "memory_read": {
            "mode": "runtime_on_demand_query",
            "enabled": True,
            "session_summary": {
                "enabled": session_summary_enabled,
                "scope": "session",
                "kind": "session_summary",
                "priority": "before_generic_memories",
                "max_results": 1,
                "counts_toward_existing_budgets": True,
            },
        },
        "memory_write": {
            "mode": "executor_promotion",
            "enabled": True,
        },
        "session_synthesis": {
            "mode": "post_turn_periodic",
            "enabled": session_synthesis_enabled,
            "turn_interval": session_synthesis_turn_interval(environment=environment),
            "summary_scope": "session",
            "summary_kind": "session_summary",
            "summary_memory_id_mode": "stable_latest_per_session",
            "builder": "deterministic_v1",
        },
        "memory_review": {
            "mode": "post_turn",
            "enabled": review_enabled,
        },
        "remember_intent_direct_write": {
            "mode": "post_turn_direct_write",
            "enabled": review_enabled
            and is_remember_intent_direct_write_enabled(environment=environment),
        },
        "skill_review": {
            "mode": "suggest",
            "enabled": review_enabled and bool(normalized_skill_refs),
            "requires_skill_refs": True,
            "skill_refs": normalized_skill_refs,
        },
        "continuity": {
            "mode": "execution_session_handoff",
            "enabled": True,
            "requested_mode": str(execution_mode).strip() or "stateless",
        },
    }


def build_api_server_conversation_workflow_contract(
    *,
    skill_refs: Sequence[str] | None = None,
    execution_mode: str = "stateless",
    environment: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Build the machine-readable rollout contract for the api_server conversation slice."""
    return build_conversation_workflow_contract(
        source="api_server",
        skill_refs=skill_refs,
        execution_mode=execution_mode,
        environment=environment,
    )


def review_capability_gate(
    *,
    source: str,
    task_type: str,
    metadata: Mapping[str, Any],
    capability: str,
) -> tuple[bool | None, str | None]:
    """Return a workflow-contract decision for review capabilities, or None for legacy paths."""

    if task_type != "conversation":
        return None, None

    contract = metadata.get("workflow_contract")
    if not isinstance(contract, Mapping):
        return (False, "workflow_not_adopted") if source == "api_server" else (None, None)
    if str(contract.get("source") or "").strip() != source:
        return False, "workflow_not_adopted"
    if str(contract.get("task_type") or "").strip() != task_type:
        return False, "workflow_not_adopted"
    if not bool(contract.get("adoption_enabled")):
        return False, "workflow_contract_disabled"

    capability_contract = contract.get(capability)
    if not isinstance(capability_contract, Mapping):
        return False, "workflow_contract_disabled"
    if bool(capability_contract.get("enabled")):
        return True, None
    if capability == "skill_review" and bool(capability_contract.get("requires_skill_refs")):
        return False, "skill_refs_required"
    return False, "workflow_contract_disabled"


def parse_allowed_sources(
    env_name: str,
    *,
    default_sources: Sequence[str],
    environment: Mapping[str, str] | None = None,
) -> set[str]:
    """Resolve an optional comma-separated allowlist, with a safe default."""

    env = environment or os.environ
    configured_sources = str(env.get(env_name) or "").strip()
    if not configured_sources:
        return {str(source).strip() for source in default_sources if str(source).strip()}
    return {
        item.strip()
        for item in configured_sources.split(",")
        if item.strip()
    }
