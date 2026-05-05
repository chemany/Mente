from pathlib import Path


def test_codex_ingestion_inventory_declares_required_kernel_areas():
    inventory_path = (
        Path(__file__).resolve().parents[2]
        / "docs/plans/2026-04-30-mente-codex-ingestion-inventory.md"
    )

    assert inventory_path.exists()

    content = inventory_path.read_text(encoding="utf-8").lower()

    required_sections = [
        "runtime / execution loop",
        "session protocol",
        "tools",
        "plugins",
        "skills",
        "sandbox/runtime",
        "config/auth surface",
        "cli/front-door surface",
    ]

    for section in required_sections:
        assert section in content


def test_kernel_boundary_map_declares_runtime_and_kernel_ownership_rules():
    boundary_map_path = (
        Path(__file__).resolve().parents[2]
        / "docs/plans/2026-04-30-mente-kernel-boundary-map.md"
    )

    assert boundary_map_path.exists()

    content = boundary_map_path.read_text(encoding="utf-8").lower()

    required_statements = [
        "stays in `mente/`",
        "moves to `kernel/codex/`",
        "adapter-only for now",
        "no product logic in kernel",
    ]

    for statement in required_statements:
        assert statement in content


def test_phase_c_migration_sequence_declares_slice_order_and_rollback_boundary():
    migration_sequence_path = (
        Path(__file__).resolve().parents[2]
        / "docs/plans/2026-04-30-mente-phase-c-migration-sequence.md"
    )

    assert migration_sequence_path.exists()

    content = migration_sequence_path.read_text(encoding="utf-8").lower()

    required_statements = [
        "ingestion order",
        "first vendoring slice",
        "validation gates after each slice",
        "rollback boundary",
    ]

    for statement in required_statements:
        assert statement in content


def test_phase_c1_manifest_declares_vendored_slice_boundary():
    manifest_path = (
        Path(__file__).resolve().parents[2]
        / "docs/plans/2026-04-30-mente-phase-c1-kernel-slice-manifest.md"
    )

    assert manifest_path.exists()

    content = manifest_path.read_text(encoding="utf-8").lower()

    required_statements = [
        "runtime protocol",
        "minimal session protocol",
        "launcher",
        "sandbox workspace helpers",
        "stays in `mente/`",
        "bridge-tool policy",
        "public `codex` cli is still the transport backend",
        "deferred",
        "plugins",
        "skills",
    ]

    for statement in required_statements:
        assert statement in content


def test_phase_c2_manifest_declares_runner_transport_and_deferred_boundaries():
    manifest_path = (
        Path(__file__).resolve().parents[2]
        / "docs/plans/2026-04-30-mente-phase-c2-kernel-runner-manifest.md"
    )

    assert manifest_path.exists()

    content = manifest_path.read_text(encoding="utf-8").lower()

    required_statements = [
        "runner",
        "cli transport backend",
        "result normalization",
        "stays in `mente/`",
        "runtime config resolution",
        "private runtime home",
        "bridge-tool policy",
        "deferred",
        "real sessionful execution path",
        "plugins",
        "skills",
    ]

    for statement in required_statements:
        assert statement in content


def test_phase_c3_snapshot_manifest_declares_upstream_source_and_patch_boundary():
    manifest_path = (
        Path(__file__).resolve().parents[2]
        / "docs/plans/2026-04-30-mente-codex-upstream-snapshot-manifest.md"
    )

    assert manifest_path.exists()

    content = manifest_path.read_text(encoding="utf-8").lower()

    required_statements = [
        "upstream codex repository source",
        "pinned snapshot identifier",
        "ingestion date",
        "local edits inside the vendored snapshot",
        "kernel/codex/upstream/",
        "kernel/codex/bridge/",
        "kernel/codex/patches/",
        "source of truth",
        "pristine as possible",
    ]

    for statement in required_statements:
        assert statement in content



def test_phase_c4_cutover_manifest_declares_bridge_switch_and_deferred_boundaries():
    manifest_path = (
        Path(__file__).resolve().parents[2]
        / "docs/plans/2026-04-30-mente-phase-c4-cutover-manifest.md"
    )

    assert manifest_path.exists()

    content = manifest_path.read_text(encoding="utf-8").lower()

    required_statements = [
        "vendored codex bridge is now the main execution path",
        "codexkerneladapter remains the only upper-layer handoff seam",
        "public `codex` binary no longer defines the architectural control plane",
        "selected front door",
        "deferred",
        "tools",
        "plugins",
        "skills",
    ]

    for statement in required_statements:
        assert statement in content


def test_phase_c5_boundary_manifest_declares_capability_ownership_split():
    manifest_path = (
        Path(__file__).resolve().parents[2]
        / "docs/plans/2026-04-30-mente-phase-c5-capability-boundary-manifest.md"
    )

    assert manifest_path.exists()

    content = manifest_path.read_text(encoding="utf-8").lower()

    required_statements = [
        "vendored codex native capability surface is active",
        "mente bridge tools remain outside kernel",
        "plugin hooks belong to codex",
        "skill loading hooks belong to codex",
        "product integration remains in `mente/`",
        "codexkerneladapter remains the only upper-layer handoff seam",
    ]

    for statement in required_statements:
        assert statement in content


def test_c6_upgrade_policy_doc_declares_release_and_snapshot_rules():
    policy_path = (
        Path(__file__).resolve().parents[2]
        / "docs/plans/2026-04-30-mente-codex-upgrade-policy.md"
    )

    assert policy_path.exists()

    content = policy_path.read_text(encoding="utf-8").lower()

    required_statements = [
        "same-snapshot mente release",
        "new upstream snapshot upgrade",
        "c3/c4/c5/c6 re-verification pass",
        ".mente-install.json",
        "git_tag_release",
        "mente_codex_runtime_bin",
        "artifact_manifest_and_runtime_wheel",
    ]

    for statement in required_statements:
        assert statement in content


def test_c6_verification_and_rollback_doc_declares_release_frozen_rollback_inputs():
    policy_path = (
        Path(__file__).resolve().parents[2]
        / "docs/plans/2026-04-30-mente-c6-verification-and-rollback.md"
    )

    assert policy_path.exists()

    content = policy_path.read_text(encoding="utf-8").lower()

    required_statements = [
        "public `codex` fallback is disabled",
        ".mente-install.json",
        "prior release id",
        "prior runtime artifact manifest",
        "prior runtime wheel",
        "mente_codex_runtime_bin",
        "runtime_not_bootstrapped",
    ]

    for statement in required_statements:
        assert statement in content
