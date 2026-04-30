from mente.executors import ToolExposurePolicy


def test_tool_exposure_policy_serializes_native_and_bridge_tools():
    policy = ToolExposurePolicy(
        policy_id="gateway:engineering",
        source="gateway",
        native_tools=["shell", "apply_patch"],
        bridge_tools=["mente_memory_query", "mente_task_lookup"],
        session_capable=False,
    )

    assert policy.model_dump(mode="json") == {
        "policy_id": "gateway:engineering",
        "source": "gateway",
        "native_tools": ["shell", "apply_patch"],
        "bridge_tools": ["mente_memory_query", "mente_task_lookup"],
        "session_capable": False,
    }


def test_tool_exposure_policy_can_mark_session_capable_visibility():
    policy = ToolExposurePolicy(
        native_tools=["native_terminal"],
        bridge_tools=["mente_session_notify"],
        session_capable=True,
    )

    assert policy.session_capable is True
    assert policy.native_tools == ["native_terminal"]
    assert policy.bridge_tools == ["mente_session_notify"]
