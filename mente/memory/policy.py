"""Deterministic memory policy models and resolution helpers."""

from __future__ import annotations

from pydantic import BaseModel

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
                return policy

        raise KeyError(f"missing default memory policy: {self.default_policy_id}")
