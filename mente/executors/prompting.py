"""Shared prompt rendering helpers for Codex-backed execution."""

from __future__ import annotations

import hashlib
from typing import Any

from mente.task_core.models import ExecutionRequest


def render_execution_prompt(request: ExecutionRequest) -> str:
    """Build a stable textual prompt from an execution request."""
    lines = [
        f"Objective: {request.objective}",
        f"Task Type: {request.task_type}",
        f"User Request: {request.user_request}",
    ]

    if request.constraints:
        lines.append("Constraints:")
        lines.extend(f"- {item}" for item in request.constraints)
    if request.acceptance_criteria:
        lines.append("Acceptance Criteria:")
        lines.extend(f"- {item}" for item in request.acceptance_criteria)
    if request.memory_facts:
        lines.append("Memory Facts:")
        lines.extend(f"- {item}" for item in request.memory_facts)
    if request.skill_refs:
        lines.append("Skill References:")
        lines.extend(f"- {item}" for item in request.skill_refs)
    lines.extend(
        [
            "Response Contract:",
            "- Return a JSON object that matches the provided output schema.",
            "- assistant_summary: brief final answer for the user.",
            "- memory_candidates: durable user or task facts worth remembering later.",
            "- If no memory facts are provided, do not fabricate prior user preferences or project conventions.",
        ]
    )

    return "\n".join(lines)


def build_prompt_fingerprint(prompt: str) -> str:
    """Return a stable fingerprint for a rendered prompt."""
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()


def build_prompt_metrics(request: ExecutionRequest) -> dict[str, Any]:
    """Compute prompt metrics from the actual rendered prompt."""
    prompt = render_execution_prompt(request)
    return {
        "prompt_char_count": len(prompt),
        "memory_fact_count": len(request.memory_facts),
        "memory_char_count": sum(len(fact) for fact in request.memory_facts),
        "prompt_fingerprint": build_prompt_fingerprint(prompt),
    }
