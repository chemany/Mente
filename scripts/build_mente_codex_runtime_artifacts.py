#!/usr/bin/env python3
"""Build frozen vendored Codex runtime artifacts for a Mente release."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import shutil
import sys
from pathlib import Path
import tempfile

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from kernel.codex.release.manifest import current_platform_tag

UPSTREAM_STAGING_SCRIPT = (
    REPO_ROOT / "kernel/codex/upstream/sdk/python/scripts/update_sdk_artifacts.py"
)
PYPROJECT_FILE = REPO_ROOT / "pyproject.toml"


def read_mente_release() -> str:
    for line in PYPROJECT_FILE.read_text(encoding="utf-8").splitlines():
        if line.startswith("version = "):
            return line.split('"')[1]
    raise RuntimeError("Could not determine Mente release version from pyproject.toml")


def load_upstream_staging_module():
    spec = importlib.util.spec_from_file_location(
        "mente_upstream_update_sdk_artifacts",
        UPSTREAM_STAGING_SCRIPT,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load upstream staging script: {UPSTREAM_STAGING_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_manifest(
    *,
    output_dir: Path,
    mente_release: str,
    codex_version: str,
    platform_tag: str,
    wheel_path: Path | None,
) -> Path:
    artifact_manifest_path = output_dir / "mente-codex-runtime-artifact-manifest.json"
    artifacts: list[dict[str, object]] = []
    if wheel_path is not None:
        artifacts.append(
            {
                "kind": "runtime-wheel",
                "platform_tag": platform_tag,
                "filename": wheel_path.name,
                "path": str(wheel_path),
                "sha256": sha256_file(wheel_path),
            }
        )
    payload = {
        "schema_version": 1,
        "mente_release": mente_release,
        "upstream_snapshot": "8f3c06cc97bbb045fe5790a6388625c0db35af7f",
        "codex_version": codex_version,
        "platform_tag": platform_tag,
        "source_staging_script": str(UPSTREAM_STAGING_SCRIPT.relative_to(REPO_ROOT)),
        "artifact_manifest": artifact_manifest_path.name,
        "artifacts": artifacts,
    }
    artifact_manifest_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return artifact_manifest_path


def build_runtime_artifact(
    *,
    mente_release: str,
    codex_version: str,
    runtime_binary: Path,
    platform_tag: str,
    output_dir: Path,
) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    upstream = load_upstream_staging_module()
    from setuptools.build_meta import build_wheel

    with tempfile.TemporaryDirectory(prefix="mente-codex-runtime-stage-") as staging_root_raw:
        staging_root = Path(staging_root_raw)
        stage_dir = staging_root / "python-runtime"
        upstream.stage_python_runtime_package(
            stage_dir,
            codex_version,
            runtime_binary.resolve(),
            platform_tag,
        )

        old_cwd = Path.cwd()
        try:
            os.chdir(stage_dir)
            wheel_name = build_wheel(str(output_dir))
        finally:
            os.chdir(old_cwd)

    wheel_path = output_dir / wheel_name
    manifest_path = write_manifest(
        output_dir=output_dir,
        mente_release=mente_release,
        codex_version=codex_version,
        platform_tag=platform_tag,
        wheel_path=wheel_path,
    )
    return manifest_path, wheel_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build frozen vendored Codex runtime artifacts for a Mente release.",
    )
    parser.add_argument(
        "--mente-release",
        default=read_mente_release(),
        help="Mente release version that owns the frozen runtime contract.",
    )
    parser.add_argument(
        "--codex-version",
        default=None,
        help="Codex runtime package version. Defaults to the vendored upstream SDK version.",
    )
    parser.add_argument(
        "--runtime-binary",
        type=Path,
        help="Path to the compiled vendored Codex runtime binary to stage into the runtime package.",
    )
    parser.add_argument(
        "--platform-tag",
        default=current_platform_tag(),
        help="Frozen platform tag for the artifact contract.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=REPO_ROOT / "dist" / "codex-runtime",
        help="Directory where wheels and the artifact manifest will be written.",
    )
    parser.add_argument(
        "--describe-only",
        action="store_true",
        help="Write only the artifact manifest contract without building a wheel.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    upstream = load_upstream_staging_module()
    codex_version = args.codex_version or upstream.current_sdk_version()

    if args.describe_only:
        manifest_path = write_manifest(
            output_dir=args.output_dir,
            mente_release=args.mente_release,
            codex_version=codex_version,
            platform_tag=args.platform_tag,
            wheel_path=None,
        )
        print(manifest_path)
        return 0

    if args.runtime_binary is None:
        parser.error("--runtime-binary is required unless --describe-only is used")

    manifest_path, wheel_path = build_runtime_artifact(
        mente_release=args.mente_release,
        codex_version=codex_version,
        runtime_binary=args.runtime_binary,
        platform_tag=args.platform_tag,
        output_dir=args.output_dir,
    )
    print(wheel_path)
    print(manifest_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
