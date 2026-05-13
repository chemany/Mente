from kernel.codex.bridge.tool_surface import (
    filter_vendored_native_tools,
    get_vendored_capability_surface,
    get_vendored_native_tool_names,
)
from mente.executors import ToolExposurePolicy, resolve_tool_exposure_policy


EXPECTED_GATEWAY_BRIDGE_TOOLS: list[str] = []
EXPECTED_API_SERVER_BRIDGE_TOOLS = [
    "mente_memory_query",
    "mente_memory_save",
]
EXPECTED_TUI_BRIDGE_TOOLS: list[str] = []


def test_tool_exposure_policy_serializes_native_and_bridge_tools_with_sources():
    policy = ToolExposurePolicy(
        policy_id="gateway:engineering",
        source="gateway",
        native_tools=["shell", "apply_patch"],
        bridge_tools=["mente_memory_query", "mente_task_lookup"],
        session_capable=False,
        native_tool_source="kernel/codex/upstream/codex-rs/tools/src/lib.rs",
        bridge_tool_source="mente/executors/bridge_tools.py",
    )

    assert policy.model_dump(mode="json") == {
        "policy_id": "gateway:engineering",
        "source": "gateway",
        "native_tools": ["shell", "apply_patch"],
        "bridge_tools": ["mente_memory_query", "mente_task_lookup"],
        "session_capable": False,
        "native_tool_source": "kernel/codex/upstream/codex-rs/tools/src/lib.rs",
        "bridge_tool_source": "mente/executors/bridge_tools.py",
    }



def test_resolve_tool_exposure_policy_filters_vendored_surface_and_keeps_bridge_tools_separate(
    monkeypatch,
):
    monkeypatch.setenv("MENTE_MEMORY_READ_TOOL_ENABLED", "1")
    monkeypatch.setenv("MENTE_MEMORY_WRITE_TOOL_ENABLED", "1")
    surface = get_vendored_capability_surface()
    vendored_native_tools = get_vendored_native_tool_names()
    policy = resolve_tool_exposure_policy(source="gateway", task_type="conversation")

    assert policy.native_tool_source == surface.native_tools.source_path
    assert policy.bridge_tool_source == "mente/executors/bridge_tools.py"
    assert policy.native_tools == vendored_native_tools
    assert policy.bridge_tools == EXPECTED_GATEWAY_BRIDGE_TOOLS
    assert policy.session_capable is True
    assert all(tool not in policy.native_tools for tool in policy.bridge_tools)


def test_resolve_tool_exposure_policy_keeps_generic_gateway_conversation_off_bridge_mcp_by_default():
    policy = resolve_tool_exposure_policy(source="gateway", task_type="conversation")

    assert policy.bridge_tools == EXPECTED_GATEWAY_BRIDGE_TOOLS


def test_resolve_tool_exposure_policy_narrows_content_publishing_bridge_tools():
    policy = resolve_tool_exposure_policy(
        source="gateway",
        task_type="conversation",
        task_profile="content_publishing",
    )

    assert policy.session_capable is True
    assert policy.bridge_tools == ["mente_wechat_publish_draft"]


def test_resolve_tool_exposure_policy_exposes_all_vendored_native_tools_for_api_server(
    monkeypatch,
):
    monkeypatch.setenv("MENTE_MEMORY_READ_TOOL_ENABLED", "1")
    monkeypatch.setenv("MENTE_MEMORY_WRITE_TOOL_ENABLED", "1")

    policy = resolve_tool_exposure_policy(source="api_server", task_type="conversation")

    assert policy.native_tools == get_vendored_native_tool_names()
    assert policy.bridge_tools == EXPECTED_API_SERVER_BRIDGE_TOOLS
    assert policy.session_capable is True
    assert all(tool not in policy.native_tools for tool in policy.bridge_tools)


def test_resolve_tool_exposure_policy_keeps_generic_tui_conversation_off_bridge_mcp_by_default():
    policy = resolve_tool_exposure_policy(source="tui", task_type="conversation")

    assert policy.native_tools == get_vendored_native_tool_names()
    assert policy.bridge_tools == EXPECTED_TUI_BRIDGE_TOOLS
    assert policy.session_capable is True



def test_tool_exposure_policy_can_mark_session_capable_visibility():
    policy = ToolExposurePolicy(
        native_tools=["native_terminal"],
        bridge_tools=["mente_session_notify"],
        session_capable=True,
    )

    assert policy.session_capable is True
    assert policy.native_tools == ["native_terminal"]
    assert policy.bridge_tools == ["mente_session_notify"]
