from kernel.codex.bridge.tool_surface import (
    filter_vendored_native_tools,
    get_vendored_capability_surface,
)
from mente.executors import ToolExposurePolicy, resolve_tool_exposure_policy


EXPECTED_GATEWAY_NATIVE_TOOLS = [
    "apply_patch",
    "exec_command",
    "request_user_input",
    "update_plan",
    "view_image",
    "write_stdin",
]
EXPECTED_GATEWAY_BRIDGE_TOOLS = [
    "mente_memory_query",
    "mente_task_lookup",
    "mente_session_notify",
]


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



def test_resolve_tool_exposure_policy_filters_vendored_surface_and_keeps_bridge_tools_separate():
    surface = get_vendored_capability_surface()
    policy = resolve_tool_exposure_policy(source="gateway", task_type="conversation")

    assert policy.native_tool_source == surface.native_tools.source_path
    assert policy.bridge_tool_source == "mente/executors/bridge_tools.py"
    assert policy.native_tools == filter_vendored_native_tools(EXPECTED_GATEWAY_NATIVE_TOOLS)
    assert policy.bridge_tools == EXPECTED_GATEWAY_BRIDGE_TOOLS
    assert all(tool not in policy.native_tools for tool in policy.bridge_tools)



def test_tool_exposure_policy_can_mark_session_capable_visibility():
    policy = ToolExposurePolicy(
        native_tools=["native_terminal"],
        bridge_tools=["mente_session_notify"],
        session_capable=True,
    )

    assert policy.session_capable is True
    assert policy.native_tools == ["native_terminal"]
    assert policy.bridge_tools == ["mente_session_notify"]
