"""Explicit Mente-owned tool exposure policy models."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ToolExposurePolicy(BaseModel):
    """Resolved tool visibility contract for an execution request."""

    native_tools: list[str] = Field(default_factory=list)
    bridge_tools: list[str] = Field(default_factory=list)
    session_capable: bool = False
    policy_id: str | None = None
    source: str | None = None

    def as_metadata(self) -> dict[str, object]:
        """Serialize the policy for request and result metadata surfaces."""
        return self.model_dump(mode="json")
