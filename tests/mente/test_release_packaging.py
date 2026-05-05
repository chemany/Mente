"""Regression tests for C6 release-packaging entrypoints."""

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_runtime_artifact_builder_script_exists():
    script_path = REPO_ROOT / "scripts" / "build_mente_codex_runtime_artifacts.py"
    assert script_path.exists()


def test_readme_exposes_mente_as_primary_command():
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")

    assert "# Mente Agent" in readme
    assert "mente" in readme
    assert "start chatting!" in readme
    assert "legacy `hermes` entrypoints remain as compatibility aliases" not in readme
