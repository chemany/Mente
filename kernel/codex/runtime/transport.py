"""Transport contracts for vendored Codex kernel execution backends."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from kernel.codex.runtime.protocol import KernelExecutionPayload
from kernel.codex.session.protocol import KernelSessionRequest


class KernelTransportRequest(BaseModel):
    """Narrow transport input assembled by the vendored kernel runner."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    payload: KernelExecutionPayload
    session: KernelSessionRequest
    runtime_config: Any
    sandbox: str
    approval_policy: str
    cwd: str
    workdir: str
    output_last_message: str
    output_schema: str
    add_dirs: list[str] = Field(default_factory=list)


class KernelTransportResponse(BaseModel):
    """Transport-specific execution output before kernel normalization."""

    command: list[str] = Field(default_factory=list)
    returncode: int | None = None
    stdout: str = ""
    stderr: str = ""
    raw_output: str = ""
    backend_failure: str | None = None


@runtime_checkable
class KernelTransport(Protocol):
    """Transport backend contract used by the vendored kernel runner."""

    def execute(self, request: KernelTransportRequest) -> KernelTransportResponse:
        """Execute one transport request and return raw backend output."""
