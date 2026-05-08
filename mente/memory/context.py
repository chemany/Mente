"""Shared helpers for building executor-facing memory context."""

from __future__ import annotations

from collections.abc import Mapping
import hashlib

from mente.memory.fact_normalization import build_fact_identity, normalize_memory_fact_text
from mente.memory.models import MemoryBuildTrace, MemoryRecord, MemoryTraceItem
from mente.memory.policy import MemoryPolicyResolver, truncate_for_policy
from mente.memory.repository import MemoryRepository
from mente.task_core.models import ExecutionRequest, Task


def resolve_memory_read_mode(task: Task | ExecutionRequest) -> str:
    """Return how the current task should receive Mente-managed memory."""

    if _has_on_demand_memory_query_tool(task):
        return "runtime_on_demand_query"
    return "shared_repository_preload"


def uses_on_demand_memory(task: Task | ExecutionRequest) -> bool:
    """Return whether Mente should keep repository memory out of the prompt."""

    return resolve_memory_read_mode(task) == "runtime_on_demand_query"


def resolve_memory_context(
    task: Task,
    *,
    memory_repository: MemoryRepository | None,
    memory_limit: int,
    memory_policy_resolver: MemoryPolicyResolver | None = None,
) -> tuple[list[str], MemoryBuildTrace]:
    """Return merged memory facts and diagnostics for a task."""

    task_memory_facts = list(task.memory_facts)
    policy_resolver = memory_policy_resolver or MemoryPolicyResolver.default()
    policy = policy_resolver.resolve(task)
    trace = MemoryBuildTrace(policy_id=policy.policy_id)
    if memory_repository is None or memory_limit <= 0:
        trace.injected_count = 0
        return task_memory_facts, trace

    source = str(task.metadata.get("source") or "").strip() or None
    seen_retrieved_ids: set[str] = set()
    session_summary_kind = policy.session_summary_kind or "session_summary"
    retrieved = memory_repository.list_relevant(
        session_id=task.session_id,
        task_type=task.task_type,
        limit=memory_limit,
        source=source,
    )
    existing = set(task_memory_facts)
    memory_facts: list[str] = []
    selected_summary_ids: set[str] = set()

    if policy.session_summary_retrieval_enabled:
        summary_records = memory_repository.list_relevant_by_scope(
            session_id=task.session_id,
            task_type=task.task_type,
            memory_scope=policy.session_summary_scope or "session",
            limit=policy.max_session_summary_results,
            source=source,
            kind=policy.session_summary_kind,
        )
        for record in summary_records:
            seen_retrieved_ids.add(record.memory_id)
            if record.scope not in policy.allowed_injection_scopes:
                trace.skipped.append(
                    MemoryTraceItem(
                        memory_id=record.memory_id,
                        scope=record.scope,
                        kind=record.kind,
                        fact=record.fact,
                        reason="scope_filtered",
                    )
                )
                continue

            if _try_inject_record(
                record,
                existing=existing,
                memory_facts=memory_facts,
                trace=trace,
                memory_limit=memory_limit,
                max_injected_memories=policy.max_injected_memories,
                max_total_injected_chars=policy.max_total_injected_chars,
                max_chars=policy.max_chars_per_session_summary,
                selected_reason="session_summary_priority",
            ):
                selected_summary_ids.add(record.memory_id)

    allowed_records = []
    filtered_records = []
    for record in retrieved:
        seen_retrieved_ids.add(record.memory_id)
        if record.memory_id in selected_summary_ids:
            continue
        if record.kind == session_summary_kind:
            trace.skipped.append(
                MemoryTraceItem(
                    memory_id=record.memory_id,
                    scope=record.scope,
                    kind=record.kind,
                    fact=record.fact,
                    reason="session_summary_filtered",
                )
            )
            continue
        if record.scope in policy.allowed_injection_scopes:
            allowed_records.append(record)
        else:
            filtered_records.append(record)

    for record in allowed_records:
        _try_inject_record(
            record,
            existing=existing,
            memory_facts=memory_facts,
            trace=trace,
            memory_limit=memory_limit,
            max_injected_memories=policy.max_injected_memories,
            max_total_injected_chars=policy.max_total_injected_chars,
            max_chars=policy.max_chars_per_injected_fact,
            selected_reason="scope_match",
        )

    for record in filtered_records:
        trace.skipped.append(
            MemoryTraceItem(
                memory_id=record.memory_id,
                scope=record.scope,
                kind=record.kind,
                fact=record.fact,
                reason="scope_filtered",
            )
        )

    trace.retrieved_count = len(seen_retrieved_ids)
    trace.injected_count = len(trace.selected)
    memory_facts.extend(task_memory_facts)
    return memory_facts, trace


def _has_on_demand_memory_query_tool(task: Task | ExecutionRequest) -> bool:
    if getattr(task, "task_type", None) != "conversation":
        return False
    tool_policy_attr = getattr(task, "tool_policy", None)
    if isinstance(tool_policy_attr, Mapping):
        bridge_tools = tool_policy_attr.get("bridge_tools")
        if isinstance(bridge_tools, (list, tuple, set)):
            if "mente_memory_query" in {
                str(item).strip()
                for item in bridge_tools
                if str(item).strip()
            }:
                return True
    metadata = getattr(task, "metadata", None)
    if not isinstance(metadata, Mapping):
        return False
    tool_policy = metadata.get("tool_policy")
    if not isinstance(tool_policy, Mapping):
        return False
    bridge_tools = tool_policy.get("bridge_tools")
    if not isinstance(bridge_tools, (list, tuple, set)):
        return False
    return "mente_memory_query" in {
        str(item).strip()
        for item in bridge_tools
        if str(item).strip()
    }


def resolve_explicit_memory_read(
    task: Task,
    *,
    memory_repository: MemoryRepository | None,
    requested_scope: str | None = None,
    requested_limit: int | None = None,
    memory_policy_resolver: MemoryPolicyResolver | None = None,
) -> tuple[list[MemoryRecord], str | None]:
    """Return policy-bounded memory records for explicit in-turn reads."""

    policy_resolver = memory_policy_resolver or MemoryPolicyResolver.default()
    policy = policy_resolver.resolve(task)
    internal_only_kinds = (policy.session_summary_kind or "session_summary",)
    if memory_repository is None:
        return [], "memory_repository_unavailable"
    if not policy.explicit_read_enabled:
        return [], "policy_disabled"
    source = str(task.metadata.get("source") or "").strip()
    if not source:
        return [], "missing_source"

    allowed_scopes = list(policy.allowed_explicit_read_scopes)
    if requested_scope is not None:
        if requested_scope not in {"session", "task_type", "global"}:
            return [], f"invalid_scope:{requested_scope}"
        if requested_scope not in allowed_scopes:
            return [], f"scope_not_allowed:{requested_scope}"
        scopes = [requested_scope]
    else:
        scopes = allowed_scopes

    max_results = policy.max_explicit_read_results
    if requested_limit is not None:
        max_results = min(max_results, max(1, requested_limit))
    if max_results <= 0:
        return [], None

    results: list[MemoryRecord] = []
    remaining = max_results
    for scope in scopes:
        if remaining <= 0:
            break
        records = memory_repository.list_relevant_by_scope(
            session_id=task.session_id,
            task_type=task.task_type,
            memory_scope=scope,
            limit=remaining,
            source=source,
            exclude_kinds=internal_only_kinds,
        )
        for record in records:
            results.append(
                record.model_copy(
                    update={
                        "fact": truncate_for_policy(
                            record.fact,
                            policy.max_chars_per_explicit_read_fact,
                        )
                    }
                )
            )
        remaining = max_results - len(results)
    return results, None


def persist_explicit_memory_write(
    task: Task,
    *,
    fact: str,
    memory_repository: MemoryRepository | None,
    requested_scope: str | None = None,
    memory_policy_resolver: MemoryPolicyResolver | None = None,
    tool_name: str = "mente_memory_save",
    write_origin: str = "explicit_memory_write",
) -> tuple[MemoryRecord | None, str | None]:
    """Persist an explicit in-turn memory write through policy-bounded storage."""

    policy_resolver = memory_policy_resolver or MemoryPolicyResolver.default()
    policy = policy_resolver.resolve(task)
    if memory_repository is None:
        return None, "memory_repository_unavailable"
    if not policy.explicit_write_enabled:
        return None, "policy_disabled"
    source = str(task.metadata.get("source") or "").strip()
    if not source:
        return None, "missing_source"

    normalized_fact = normalize_memory_fact_text(fact)
    persisted_fact = truncate_for_policy(
        normalized_fact,
        policy.max_chars_per_explicit_write_fact,
    )
    if not persisted_fact:
        return None, "empty_fact"

    scope, scope_reason = _resolve_explicit_write_scope(
        task,
        requested_scope=requested_scope,
        allowed_scopes=policy.allowed_explicit_write_scopes,
    )
    if scope_reason is not None:
        return None, scope_reason

    return persist_memory_fact(
        task,
        fact=persisted_fact,
        memory_repository=memory_repository,
        scope=scope,
        source=source,
        tool_name=tool_name,
        write_origin=write_origin,
    )


def persist_memory_fact(
    task: Task,
    *,
    fact: str,
    memory_repository: MemoryRepository | None,
    scope: str,
    source: str,
    tool_name: str,
    write_origin: str,
    memory_id: str | None = None,
) -> tuple[MemoryRecord | None, str | None]:
    """Persist one normalized fact with exact dedup and narrow supersede semantics."""

    if memory_repository is None:
        return None, "memory_repository_unavailable"

    identity = build_fact_identity(fact)
    if not identity.normalized_fact:
        return None, "empty_fact"

    metadata = {
        "promotion_reason": write_origin,
        "tool_name": tool_name,
        "write_origin": write_origin,
        "task_id": task.task_id,
        "session_id": task.session_id,
        "source": source,
        "task_type": task.task_type,
    }
    record = MemoryRecord(
        memory_id=memory_id
        or _build_explicit_memory_id(
            task_id=task.task_id,
            scope=scope,
            fact=identity.normalized_fact,
        ),
        session_id=task.session_id if scope == "session" else None,
        task_id=task.task_id,
        task_type=task.task_type,
        source=source,
        scope=scope,
        fact=identity.normalized_fact,
        fact_key=identity.fact_key,
        slot_key=identity.slot_key,
        metadata=metadata,
    )
    return memory_repository.save_resolved_fact(record)


def _try_inject_record(
    record: MemoryRecord,
    *,
    existing: set[str],
    memory_facts: list[str],
    trace: MemoryBuildTrace,
    memory_limit: int,
    max_injected_memories: int,
    max_total_injected_chars: int,
    max_chars: int,
    selected_reason: str,
) -> bool:
    normalized_fact = truncate_for_policy(record.fact, max_chars)
    prompt_fact = f"Memory: {normalized_fact}"
    if normalized_fact in existing or prompt_fact in existing:
        trace.skipped.append(
            MemoryTraceItem(
                memory_id=record.memory_id,
                scope=record.scope,
                kind=record.kind,
                fact=record.fact,
                reason="duplicate_existing_fact",
            )
        )
        return False

    if len(memory_facts) >= min(memory_limit, max_injected_memories):
        trace.skipped.append(
            MemoryTraceItem(
                memory_id=record.memory_id,
                scope=record.scope,
                kind=record.kind,
                fact=record.fact,
                reason="memory_limit_reached",
            )
        )
        return False

    if trace.prompt_budget_char_count + len(prompt_fact) > max_total_injected_chars:
        trace.skipped.append(
            MemoryTraceItem(
                memory_id=record.memory_id,
                scope=record.scope,
                kind=record.kind,
                fact=record.fact,
                reason="prompt_budget_reached",
            )
        )
        return False

    memory_facts.append(prompt_fact)
    existing.add(prompt_fact)
    trace.prompt_budget_char_count += len(prompt_fact)
    trace.selected.append(
        MemoryTraceItem(
            memory_id=record.memory_id,
            scope=record.scope,
            kind=record.kind,
            fact=record.fact,
            reason=selected_reason,
        )
    )
    return True


def _resolve_explicit_write_scope(
    task: Task,
    *,
    requested_scope: str | None,
    allowed_scopes: list[str],
) -> tuple[str, str | None]:
    if requested_scope is not None:
        if requested_scope not in {"session", "task_type", "global"}:
            return "", f"invalid_scope:{requested_scope}"
        if requested_scope not in allowed_scopes:
            return "", f"scope_not_allowed:{requested_scope}"
        return requested_scope, None

    scope = _derive_default_explicit_write_scope(task)
    if scope not in allowed_scopes:
        return "", f"scope_not_allowed:{scope}"
    return scope, None


def _derive_default_explicit_write_scope(task: Task) -> str:
    source = str(task.metadata.get("source") or "").strip()
    if task.task_type == "conversation" and source in {"gateway", "api_server", "tui"}:
        return "session"
    return "task_type"


def _build_explicit_memory_id(*, task_id: str, scope: str, fact: str) -> str:
    digest = hashlib.sha256(f"{task_id}\n{scope}\n{fact}".encode("utf-8")).hexdigest()[:12]
    return f"{task_id}:explicit_memory:{digest}"
