"""Core task and execution schemas for Mente."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator


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


class ExecutionMode(StrEnum):
    """Top-level Mente-owned execution path selection."""

    STATELESS = "stateless"
    SESSIONFUL = "sessionful"


class TaskRole(StrEnum):
    """High-level Mente-owned task role selection."""

    COORDINATOR = "coordinator"
    WORKER = "worker"


class DispatchMode(StrEnum):
    """Dispatch mode chosen for one task envelope."""

    INLINE = "inline"
    DELEGATE_BACKGROUND = "delegate_background"
    DELEGATE_FOREGROUND = "delegate_foreground"


class SessionMode(StrEnum):
    """Mente-owned session continuity mode selection."""

    START = "start"
    RESUME = "resume"


class ExecutionSession(BaseModel):
    """Mente-owned session continuity contract for one task/request."""

    mode: SessionMode
    continuity_id: str | None = None

    @model_validator(mode="after")
    def _validate_contract(self) -> "ExecutionSession":
        if self.mode is SessionMode.RESUME and not self.continuity_id:
            msg = "continuity_id is required when mode=resume"
            raise ValueError(msg)
        return self


def _normalize_execution_mode_value(value: Any) -> Any:
    if value is None or value == "":
        return ExecutionMode.STATELESS
    if isinstance(value, ExecutionMode):
        return value
    normalized = str(value).strip().lower()
    if normalized == "session":
        return ExecutionMode.SESSIONFUL
    return normalized


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
    parent_task_id: str | None = None
    job_id: str | None = None
    role: TaskRole = TaskRole.WORKER
    dispatch_mode: DispatchMode = DispatchMode.INLINE
    worker_lane: str | None = None
    worker_skill_refs: list[str] = Field(default_factory=list)
    execution_mode: ExecutionMode = ExecutionMode.STATELESS
    execution_session: ExecutionSession | None = None
    resume_token: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("execution_mode", mode="before")
    @classmethod
    def _normalize_execution_mode(cls, value: Any) -> Any:
        return _normalize_execution_mode_value(value)

    @model_validator(mode="after")
    def _normalize_execution_session(self) -> "Task":
        if self.execution_session is None and self.resume_token:
            self.execution_session = ExecutionSession(
                mode=SessionMode.RESUME,
                continuity_id=self.resume_token,
            )
        if self.execution_mode is ExecutionMode.STATELESS:
            self.execution_session = None
        elif self.execution_session is None:
            self.execution_session = ExecutionSession(mode=SessionMode.START)
        return self


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
    parent_task_id: str | None = None
    job_id: str | None = None
    role: TaskRole = TaskRole.WORKER
    dispatch_mode: DispatchMode = DispatchMode.INLINE
    worker_lane: str | None = None
    worker_skill_refs: list[str] = Field(default_factory=list)
    execution_mode: ExecutionMode = ExecutionMode.STATELESS
    execution_session: ExecutionSession | None = None
    resume_token: str | None = None
    tool_policy: dict[str, Any] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("execution_mode", mode="before")
    @classmethod
    def _normalize_execution_mode(cls, value: Any) -> Any:
        return _normalize_execution_mode_value(value)

    @field_validator("tool_policy", mode="before")
    @classmethod
    def _serialize_tool_policy(cls, value: Any) -> Any:
        if isinstance(value, BaseModel):
            return value.model_dump(mode="json", exclude_none=True)
        return value

    @model_validator(mode="after")
    def _normalize_execution_session(self) -> "ExecutionRequest":
        if self.execution_session is None and self.resume_token:
            self.execution_session = ExecutionSession(
                mode=SessionMode.RESUME,
                continuity_id=self.resume_token,
            )
        if self.execution_mode is ExecutionMode.STATELESS:
            self.execution_session = None
        elif self.execution_session is None:
            self.execution_session = ExecutionSession(mode=SessionMode.START)
        return self


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
    execution_session: ExecutionSession | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
