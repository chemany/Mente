"""Core task and execution schemas for Mente."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class TaskStatus(StrEnum):
    """Lifecycle states for a task."""

    INGESTED = "ingested"
    CLASSIFIED = "classified"
    PLANNED = "planned"
    CONTEXT_PREPARED = "context_prepared"
    EXECUTING = "executing"
    VERIFIED = "verified"
    PERSISTED = "persisted"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    BLOCKED = "blocked"


class Task(BaseModel):
    """Normalized task envelope produced by ingress."""

    task_id: str
    session_id: str
    task_type: str
    objective: str
    user_request: str
    status: TaskStatus = TaskStatus.INGESTED
    workspace: str | None = None
    constraints: list[str] = Field(default_factory=list)
    allowed_tools: list[str] = Field(default_factory=list)
    memory_facts: list[str] = Field(default_factory=list)
    skill_refs: list[str] = Field(default_factory=list)
    artifacts_in: list[str] = Field(default_factory=list)
    acceptance_criteria: list[str] = Field(default_factory=list)
    budget: dict[str, Any] = Field(default_factory=dict)
    execution_mode: str | None = None
    resume_token: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ExecutionRequest(BaseModel):
    """Structured payload handed to an executor."""

    task_id: str
    session_id: str
    task_type: str
    objective: str
    user_request: str
    workspace: str
    constraints: list[str] = Field(default_factory=list)
    allowed_tools: list[str] = Field(default_factory=list)
    memory_facts: list[str] = Field(default_factory=list)
    skill_refs: list[str] = Field(default_factory=list)
    artifacts_in: list[str] = Field(default_factory=list)
    acceptance_criteria: list[str] = Field(default_factory=list)
    budget: dict[str, Any] = Field(default_factory=dict)
    execution_mode: str | None = None
    resume_token: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ExecutionResult(BaseModel):
    """Structured result returned by an executor."""

    status: str
    summary: str
    actions_taken: list[str] = Field(default_factory=list)
    changed_files: list[str] = Field(default_factory=list)
    commands_run: list[str] = Field(default_factory=list)
    tool_calls: list[str] = Field(default_factory=list)
    artifacts_out: list[str] = Field(default_factory=list)
    verification_results: list[str] = Field(default_factory=list)
    follow_up_tasks: list[str] = Field(default_factory=list)
    memory_candidates: list[str] = Field(default_factory=list)
    raw_transcript_ref: str | None = None
    usage: dict[str, Any] = Field(default_factory=dict)
    failure_reason: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
