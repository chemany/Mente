"""Stable kernel adapter contract for kernel-backed execution."""

from __future__ import annotations

from abc import ABC, abstractmethod

from mente.executors.base import Executor
from mente.task_core.models import ExecutionRequest


class CodexKernelAdapter(Executor, ABC):
    """Adapter seam for Codex-backed execution implementations."""

    def resolve_tool_policy(self, request: ExecutionRequest) -> dict[str, object] | None:
        """Expose the resolved tool policy carried by an execution request."""
        return request.tool_policy

    @abstractmethod
    def build_request_payload(self, request: ExecutionRequest) -> dict[str, object]:
        """Build a transport-neutral payload for a prepared execution request."""
