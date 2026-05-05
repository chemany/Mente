"""Minimal session envelope types for the vendored Codex kernel slice."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, model_validator


class KernelSessionMode(StrEnum):
    """Execution modes supported by the vendored kernel contract."""

    STATELESS = "stateless"
    SESSION = "session"


class KernelSessionRequest(BaseModel):
    """Minimal session envelope used to distinguish stateless and bounded session runs."""

    mode: KernelSessionMode = KernelSessionMode.STATELESS
    session_id: str | None = None
    resume_token: str | None = None

    @model_validator(mode="after")
    def _validate_session_fields(self) -> "KernelSessionRequest":
        if self.mode is KernelSessionMode.STATELESS and self.session_id:
            msg = "session_id is only allowed when mode=session"
            raise ValueError(msg)
        return self
