"""Explicit Mente-owned outer policy over vendored Codex capabilities."""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, Field

from kernel.codex.bridge.tool_surface import (
    filter_vendored_native_tools,
    get_vendored_capability_surface,
)
from mente.executors.bridge_tools import get_bridge_tool_names, get_bridge_tool_registry


_BRIDGE_TOOL_SOURCE_PATH = "mente/executors/bridge_tools.py"


@dataclass(frozen=True)
class _PolicyProfile:
    native_tools: tuple[str, ...]
    bridge_tools: tuple[str, ...]
    session_capable: bool = False


_POLICY_PROFILES: dict[tuple[str, str], _PolicyProfile] = {
    ("cron", "cron"): _PolicyProfile(
        native_tools=("exec_command", "update_plan", "write_stdin"),
        bridge_tools=("mente_schedule_cron", "mente_task_lookup"),
    ),
    ("gateway", "conversation"): _PolicyProfile(
        native_tools=(
            "apply_patch",
            "exec_command",
            "request_user_input",
            "update_plan",
            "view_image",
            "write_stdin",
        ),
        bridge_tools=(
            "mente_memory_query",
            "mente_task_lookup",
            "mente_session_notify",
        ),
    ),
    ("api_server", "conversation"): _PolicyProfile(
        native_tools=(
            "apply_patch",
            "exec_command",
            "update_plan",
            "view_image",
            "write_stdin",
        ),
        bridge_tools=("mente_memory_query", "mente_memory_append"),
    ),
}

_DEFAULT_POLICY_PROFILE = _PolicyProfile(native_tools=(), bridge_tools=())


class ToolExposurePolicy(BaseModel):
    """Resolved tool visibility contract for an execution request."""

    native_tools: list[str] = Field(default_factory=list)
    bridge_tools: list[str] = Field(default_factory=list)
    session_capable: bool = False
    policy_id: str | None = None
    source: str | None = None
    native_tool_source: str | None = None
    bridge_tool_source: str | None = None

    def as_metadata(self) -> dict[str, object]:
        """Serialize the policy for request and result metadata surfaces."""
        return self.model_dump(mode="json")



def _filter_bridge_tools(allowed_names: tuple[str, ...]) -> list[str]:
    registry = get_bridge_tool_registry()
    unknown_names = [name for name in allowed_names if name not in registry]
    if unknown_names:
        raise ValueError(f"Unknown Mente bridge tools requested by policy: {unknown_names}")
    return [name for name in get_bridge_tool_names() if name in allowed_names]



def resolve_tool_exposure_policy(*, source: str, task_type: str) -> ToolExposurePolicy:
    """Resolve a Mente outer policy over the vendored Codex native capability surface."""

    profile = _POLICY_PROFILES.get((source, task_type), _DEFAULT_POLICY_PROFILE)
    vendored_surface = get_vendored_capability_surface()
    return ToolExposurePolicy(
        policy_id=f"{source}:{task_type}",
        source=source,
        native_tools=filter_vendored_native_tools(profile.native_tools),
        bridge_tools=_filter_bridge_tools(profile.bridge_tools),
        session_capable=profile.session_capable,
        native_tool_source=vendored_surface.native_tools.source_path,
        bridge_tool_source=_BRIDGE_TOOL_SOURCE_PATH,
    )
