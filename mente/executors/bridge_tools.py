"""Deterministic registry for the pre-fork Mente bridge tool surface."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BridgeToolDefinition:
    """Static description for a Mente bridge tool name."""

    name: str
    description: str


_BRIDGE_TOOL_REGISTRY = (
    BridgeToolDefinition(
        name="mente_memory_query",
        description="Query Mente-managed memory without exposing storage internals.",
    ),
    BridgeToolDefinition(
        name="mente_memory_append",
        description="Append a promoted memory candidate into Mente-managed memory.",
    ),
    BridgeToolDefinition(
        name="mente_task_lookup",
        description="Look up Mente task state and observability metadata.",
    ),
    BridgeToolDefinition(
        name="mente_schedule_cron",
        description="Register or update a Mente-managed cron schedule.",
    ),
    BridgeToolDefinition(
        name="mente_gateway_send",
        description="Send a message through the active Mente gateway surface.",
    ),
    BridgeToolDefinition(
        name="mente_session_notify",
        description="Emit a session-scoped notification through Mente-managed delivery.",
    ),
)


def list_bridge_tools() -> tuple[BridgeToolDefinition, ...]:
    """Return the deterministic bridge tool registry in declaration order."""
    return _BRIDGE_TOOL_REGISTRY


def get_bridge_tool_registry() -> dict[str, BridgeToolDefinition]:
    """Return the registry keyed by stable bridge tool name."""
    return {tool.name: tool for tool in _BRIDGE_TOOL_REGISTRY}


def get_bridge_tool_names() -> list[str]:
    """Return the stable registry names for policy and docs surfaces."""
    return [tool.name for tool in _BRIDGE_TOOL_REGISTRY]
