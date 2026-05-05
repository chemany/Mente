from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_c6_release_freeze_manifest_exists_and_records_current_gap_baseline():
    manifest_path = (
        REPO_ROOT / "docs/plans/2026-04-30-mente-codex-release-freeze-manifest.md"
    )

    assert manifest_path.exists()

    content = manifest_path.read_text(encoding="utf-8").lower()

    required_statements = [
        "8f3c06cc97bbb045fe5790a6388625c0db35af7f",
        "phase c4 cutover manifest",
        "phase c5 capability boundary manifest",
        "runtime binary path gap",
        "packaging/install gap",
        "release freeze",
    ]

    for statement in required_statements:
        assert statement in content


def test_c6_release_freeze_manifest_records_runtime_artifact_contract_inputs():
    manifest_path = (
        REPO_ROOT / "docs/plans/2026-04-30-mente-codex-release-freeze-manifest.md"
    )
    content = manifest_path.read_text(encoding="utf-8").lower()

    required_statements = [
        "artifact manifest",
        "platform tag",
        "sha256",
        "kernel/codex/upstream/sdk/python/scripts/update_sdk_artifacts.py",
    ]

    for statement in required_statements:
        assert statement in content
