from importlib import import_module
from pathlib import Path


def test_vendored_upstream_codex_snapshot_exists_with_recognizable_layout():
    upstream_root = Path(__file__).resolve().parents[2] / "kernel/codex/upstream"

    assert upstream_root.exists()
    assert (upstream_root / "README.md").exists()

    required_entries = [
        "codex-cli",
        "codex-rs",
        "sdk",
        "patches",
        "tools",
        "package.json",
        "justfile",
    ]

    for entry in required_entries:
        assert (upstream_root / entry).exists(), entry

    required_rust_crates = [
        "core",
        "protocol",
        "exec",
        "cli",
    ]

    for entry in required_rust_crates:
        assert (upstream_root / "codex-rs" / entry).exists(), entry


def test_vendored_snapshot_readme_declares_upstream_ownership_and_edit_policy():
    readme_path = Path(__file__).resolve().parents[2] / "kernel/codex/upstream/README.mente.md"

    assert readme_path.exists()

    content = readme_path.read_text(encoding="utf-8").lower()

    required_statements = [
        "vendored upstream source",
        "not mente-authored kernel code",
        "https://github.com/openai/codex",
        "local edits",
    ]

    for statement in required_statements:
        assert statement in content


def test_bridge_entrypoints_exist_outside_upstream_and_are_import_safe():
    bridge_root = Path(__file__).resolve().parents[2] / "kernel/codex/bridge"

    assert bridge_root.exists()
    assert (bridge_root / "__init__.py").exists()
    assert (bridge_root / "entrypoints.py").exists()
    assert "upstream" not in bridge_root.parts

    module = import_module("kernel.codex.bridge.entrypoints")

    assert hasattr(module, "get_codex_handoff_surface")


def test_bridge_manifest_declares_boundary_and_no_cutover_yet():
    manifest_path = (
        Path(__file__).resolve().parents[2]
        / "docs/plans/2026-04-30-mente-phase-c3-snapshot-bridge-manifest.md"
    )

    assert manifest_path.exists()

    content = manifest_path.read_text(encoding="utf-8").lower()

    required_statements = [
        "kernel/codex/upstream/",
        "kernel/codex/bridge/",
        "kernel/codex/patches/",
        "only allowed mente-facing call surface",
        "main execution path is unchanged",
        "cutover has not happened yet",
    ]

    for statement in required_statements:
        assert statement in content
