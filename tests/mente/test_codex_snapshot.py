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


def test_c6_patch_policy_docs_and_patch_root_exist():
    repo_root = Path(__file__).resolve().parents[2]
    patch_root = repo_root / "kernel/codex/patches"
    readme_path = patch_root / "README.md"
    policy_path = repo_root / "docs/plans/2026-04-30-mente-codex-patch-policy.md"

    assert patch_root.exists()
    assert readme_path.exists()
    assert policy_path.exists()

    readme = readme_path.read_text(encoding="utf-8").lower()
    policy = policy_path.read_text(encoding="utf-8").lower()

    for statement in [
        "default landing zone",
        "do **not** edit `kernel/codex/upstream/` by default",
        "product logic",
    ]:
        assert statement in readme

    for statement in [
        "same-snapshot mente patch",
        "new upstream snapshot upgrade",
        "kernel/codex/bridge/",
        "kernel/codex/release/",
        "kernel/codex/runtime/",
        "kernel/codex/patches/",
        "no edits inside the vendored upstream tree",
        "public `codex` fallback remains disabled",
    ]:
        assert statement in policy
