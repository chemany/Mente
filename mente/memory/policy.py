"""Deterministic memory policy models and resolution helpers."""

from __future__ import annotations

from collections.abc import Mapping

from pydantic import BaseModel, Field

from mente.task_core.models import Task


class MemoryPolicy(BaseModel):
    """Prompt-facing policy limits for memory injection and promotion."""

    policy_id: str
    allowed_injection_scopes: list[str]
    max_injected_memories: int
    max_chars_per_injected_fact: int
    max_total_injected_chars: int
    max_promoted_memories: int
    max_chars_per_promoted_fact: int
    explicit_read_enabled: bool = False
    allowed_explicit_read_scopes: list[str] = Field(default_factory=list)
    max_explicit_read_results: int = 0
    max_chars_per_explicit_read_fact: int = 0
    explicit_write_enabled: bool = False
    allowed_explicit_write_scopes: list[str] = Field(default_factory=list)
    max_chars_per_explicit_write_fact: int = 0
    session_summary_retrieval_enabled: bool = False
    session_summary_scope: str | None = None
    session_summary_kind: str | None = None
    max_session_summary_results: int = 0
    max_chars_per_session_summary: int = 0


class MemoryPolicyResolver:
    """Resolve a deterministic memory policy for a task."""

    def __init__(
        self,
        profiles: dict[str, MemoryPolicy],
        default_policy_id: str = "default",
    ) -> None:
        self.profiles = dict(profiles)
        self.default_policy_id = default_policy_id

    @classmethod
    def default(cls) -> "MemoryPolicyResolver":
        return cls(
            profiles={
                "gateway:conversation": MemoryPolicy(
                    policy_id="gateway:conversation",
                    allowed_injection_scopes=["session", "global"],
                    max_injected_memories=3,
                    max_chars_per_injected_fact=160,
                    max_total_injected_chars=480,
                    max_promoted_memories=3,
                    max_chars_per_promoted_fact=160,
                    explicit_read_enabled=True,
                    allowed_explicit_read_scopes=["session", "global"],
                    max_explicit_read_results=3,
                    max_chars_per_explicit_read_fact=160,
                    explicit_write_enabled=True,
                    allowed_explicit_write_scopes=["session", "global"],
                    max_chars_per_explicit_write_fact=160,
                ),
                "api_server:conversation": MemoryPolicy(
                    policy_id="api_server:conversation",
                    allowed_injection_scopes=["session", "global"],
                    max_injected_memories=3,
                    max_chars_per_injected_fact=160,
                    max_total_injected_chars=480,
                    max_promoted_memories=3,
                    max_chars_per_promoted_fact=160,
                    explicit_read_enabled=True,
                    allowed_explicit_read_scopes=["session", "global"],
                    max_explicit_read_results=3,
                    max_chars_per_explicit_read_fact=160,
                    explicit_write_enabled=True,
                    allowed_explicit_write_scopes=["session", "global"],
                    max_chars_per_explicit_write_fact=160,
                ),
                "tui:conversation": MemoryPolicy(
                    policy_id="tui:conversation",
                    allowed_injection_scopes=["session", "global"],
                    max_injected_memories=3,
                    max_chars_per_injected_fact=160,
                    max_total_injected_chars=480,
                    max_promoted_memories=3,
                    max_chars_per_promoted_fact=160,
                    explicit_read_enabled=True,
                    allowed_explicit_read_scopes=["session", "global"],
                    max_explicit_read_results=3,
                    max_chars_per_explicit_read_fact=160,
                    explicit_write_enabled=True,
                    allowed_explicit_write_scopes=["session", "global"],
                    max_chars_per_explicit_write_fact=160,
                ),
                "cron:cron": MemoryPolicy(
                    policy_id="cron:cron",
                    allowed_injection_scopes=["task_type", "global"],
                    max_injected_memories=2,
                    max_chars_per_injected_fact=220,
                    max_total_injected_chars=440,
                    max_promoted_memories=2,
                    max_chars_per_promoted_fact=220,
                ),
                "default": MemoryPolicy(
                    policy_id="default",
                    allowed_injection_scopes=["task_type", "global"],
                    max_injected_memories=2,
                    max_chars_per_injected_fact=180,
                    max_total_injected_chars=360,
                    max_promoted_memories=2,
                    max_chars_per_promoted_fact=180,
                ),
            }
        )

    def resolve(self, task: Task) -> MemoryPolicy:
        source = str(task.metadata.get("source") or "").strip()
        candidates = []
        if source:
            candidates.append(f"{source}:{task.task_type}")
        candidates.append(task.task_type)
        candidates.append(self.default_policy_id)

        for policy_id in candidates:
            policy = self.profiles.get(policy_id)
            if policy is not None:
                return self._apply_session_summary_contract(policy, task)

        raise KeyError(f"missing default memory policy: {self.default_policy_id}")

    def _apply_session_summary_contract(
        self,
        policy: MemoryPolicy,
        task: Task,
    ) -> MemoryPolicy:
        if task.task_type != "conversation":
            return policy

        source = str(task.metadata.get("source") or "").strip()
        if not source:
            return policy

        workflow_contract = task.metadata.get("workflow_contract")
        if not isinstance(workflow_contract, Mapping):
            return policy
        contract_source = str(workflow_contract.get("source") or "").strip()
        if contract_source and contract_source != source:
            return policy
        contract_task_type = str(workflow_contract.get("task_type") or "").strip()
        if contract_task_type and contract_task_type != task.task_type:
            return policy

        memory_read = workflow_contract.get("memory_read")
        if not isinstance(memory_read, Mapping):
            return policy
        session_summary = memory_read.get("session_summary")
        if not isinstance(session_summary, Mapping):
            return policy
        if not bool(session_summary.get("enabled")):
            return policy

        return policy.model_copy(
            update={
                "session_summary_retrieval_enabled": True,
                "session_summary_scope": str(session_summary.get("scope") or "session"),
                "session_summary_kind": str(session_summary.get("kind") or "session_summary"),
                "max_session_summary_results": _coerce_positive_int(
                    session_summary.get("max_results"),
                    default=1,
                ),
                "max_chars_per_session_summary": policy.max_chars_per_injected_fact,
            }
        )


def truncate_for_policy(text: str, max_chars: int) -> str:
    """Trim and deterministically truncate a memory fact."""
    trimmed = text.strip()
    if len(trimmed) <= max_chars:
        return trimmed
    if max_chars < 4:
        return trimmed[:max_chars]
    return trimmed[: max_chars - 3].rstrip() + "..."


def _coerce_positive_int(value: object, *, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default
