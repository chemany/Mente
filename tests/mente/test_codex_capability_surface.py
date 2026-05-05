from pathlib import Path

from mente.executors.bridge_tools import get_bridge_tool_names
from kernel.codex.bridge.tool_surface import (
    filter_vendored_native_tools,
    get_vendored_capability_surface,
    get_vendored_native_tool_names,
)


DOC_PATH = (
    Path(__file__).resolve().parents[2]
    / "docs/plans/2026-04-30-mente-codex-capability-surface-map.md"
)


def test_capability_surface_map_exists_and_points_to_vendored_upstream_sources():
    assert DOC_PATH.exists()

    content = DOC_PATH.read_text(encoding="utf-8").lower()

    required_statements = [
        "source of truth",
        "kernel/codex/upstream/codex-rs/tools/src/lib.rs",
        "kernel/codex/upstream/codex-rs/plugin/src/lib.rs",
        "kernel/codex/upstream/codex-rs/skills/src/lib.rs",
        "kernel/codex/upstream/sdk/python/src/codex_app_server/",
        "bridge tools stay outside",
    ]

    for statement in required_statements:
        assert statement in content


def test_vendored_capability_surface_is_traceable_to_vendored_sources():
    surface = get_vendored_capability_surface()

    assert surface.source_of_truth == "vendored_upstream"
    assert surface.native_tools.source_path.endswith("kernel/codex/upstream/codex-rs/tools/src/lib.rs")
    assert surface.plugin_hooks.source_path.endswith("kernel/codex/upstream/codex-rs/plugin/src/lib.rs")
    assert surface.skill_loading.source_path.endswith("kernel/codex/upstream/codex-rs/skills/src/lib.rs")
    assert "kernel/codex/upstream/sdk/python/src/codex_app_server/__init__.py" in surface.app_server_touchpoints
    assert "exec_command" in surface.native_tools.names
    assert "apply_patch" in surface.native_tools.names


def test_filtered_native_surface_preserves_vendored_order_and_excludes_bridge_tools():
    filtered = filter_vendored_native_tools([
        "write_stdin",
        "mente_memory_query",
        "exec_command",
        "apply_patch",
    ])

    assert filtered == ["apply_patch", "exec_command", "write_stdin"]


def test_bridge_tool_names_are_explicitly_excluded_from_vendored_native_surface():
    native_tool_names = set(get_vendored_native_tool_names())

    for bridge_tool_name in get_bridge_tool_names():
        assert bridge_tool_name not in native_tool_names
