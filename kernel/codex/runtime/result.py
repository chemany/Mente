"""Kernel-owned execution result contract for vendored Codex runtime flows."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class KernelExecutionResult(BaseModel):
    """Normalized result returned by the vendored kernel runner."""

    status: str
    assistant_summary: str
    memory_candidates: list[str] = Field(default_factory=list)
    commands_run: list[str] = Field(default_factory=list)
    changed_files: list[str] = Field(default_factory=list)
    artifacts_out: list[str] = Field(default_factory=list)
    verification_results: list[str] = Field(default_factory=list)
    follow_up_tasks: list[str] = Field(default_factory=list)
    debug: dict[str, Any] = Field(default_factory=dict)
    backend_failure: str | None = None
