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
