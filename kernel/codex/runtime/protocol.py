"""Transport-neutral runtime protocol for the vendored Codex kernel slice."""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field


class KernelExecutionPayload(BaseModel):
    """Stable kernel-owned request payload for stateless launcher execution."""

    prompt: str
    workspace: str
    tool_policy: dict[str, Any] | None = None


class KernelStructuredOutput(BaseModel):
    """Structured final response returned from the stateless Codex transport."""

    assistant_summary: str
    memory_candidates: list[str] = Field(default_factory=list)


def build_structured_output_schema() -> dict[str, object]:
    """Return the schema expected from the transport backend."""
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "assistant_summary": {"type": "string"},
            "memory_candidates": {
                "type": "array",
                "items": {"type": "string"},
            },
        },
        "required": ["assistant_summary", "memory_candidates"],
    }


def parse_structured_output(raw_output: str) -> KernelStructuredOutput | None:
    """Parse structured transport output, returning ``None`` on malformed data."""
    if not raw_output:
        return None

    try:
        parsed = json.loads(raw_output)
    except json.JSONDecodeError:
        return None

    if not isinstance(parsed, dict):
        return None

    try:
        return KernelStructuredOutput.model_validate(parsed)
    except Exception:
        return None

