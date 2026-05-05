from pathlib import Path
import tomllib


REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_pyproject() -> dict:
    with (REPO_ROOT / "pyproject.toml").open("rb") as handle:
        return tomllib.load(handle)


def test_release_packaging_metadata_tracks_vendored_kernel_slice():
    pyproject = _load_pyproject()
    include = pyproject["tool"]["setuptools"]["packages"]["find"]["include"]

    assert "kernel" in include
    assert "kernel.*" in include
    assert (REPO_ROOT / "kernel" / "__init__.py").exists()


def test_release_packaging_manifest_includes_kernel_and_release_freeze_metadata():
    manifest_content = (REPO_ROOT / "MANIFEST.in").read_text(encoding="utf-8")

    assert "graft kernel" in manifest_content
    assert "graft docs/plans" in manifest_content
    assert (
        REPO_ROOT / "docs/plans/2026-04-30-mente-codex-release-freeze-manifest.md"
    ).exists()


def test_release_pipeline_defines_runtime_artifact_builder_contract():
    builder_script = REPO_ROOT / "scripts/build_mente_codex_runtime_artifacts.py"
    release_script = (REPO_ROOT / "scripts/release.py").read_text(encoding="utf-8")

    assert builder_script.exists()
    assert "build_mente_codex_runtime_artifacts.py" in release_script
