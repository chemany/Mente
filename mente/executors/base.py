"""Executor interface for Mente."""

from __future__ import annotations

from abc import ABC, abstractmethod

from mente.task_core.models import ExecutionRequest, ExecutionResult


class Executor(ABC):
    """Abstract execution backend."""

    @abstractmethod
    def execute(self, request: ExecutionRequest) -> ExecutionResult:
        """Execute a prepared request and return a structured result."""

    def supports_kernel_sessions(self) -> bool:
        """Return whether this executor supports reusable kernel sessions."""
        return False
