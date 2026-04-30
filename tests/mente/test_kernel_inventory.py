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
