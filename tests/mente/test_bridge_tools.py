from pathlib import Path

from mente.executors.bridge_tools import get_bridge_tool_names, get_bridge_tool_registry


DOC_PATH = Path("docs/plans/2026-04-29-mente-codex-native-runtime-design.md")
EXPECTED_BRIDGE_TOOL_NAMES = [
    "mente_memory_query",
    "mente_memory_append",
    "mente_task_lookup",
    "mente_schedule_cron",
    "mente_gateway_send",
    "mente_session_notify",
]


def test_bridge_tool_registry_lists_expected_names_in_deterministic_order():
    assert get_bridge_tool_names() == EXPECTED_BRIDGE_TOOL_NAMES


def test_bridge_tool_registry_is_policy_addressable():
    registry = get_bridge_tool_registry()

    assert list(registry) == EXPECTED_BRIDGE_TOOL_NAMES
    assert registry["mente_memory_query"].name == "mente_memory_query"
    assert registry["mente_session_notify"].name == "mente_session_notify"


def test_native_runtime_design_declares_bridge_surface_contract():
    document = DOC_PATH.read_text(encoding="utf-8")

    assert "pre-fork bridge surface contract" in document
    assert "mente/executors/bridge_tools.py" in document
