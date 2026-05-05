#!/usr/bin/env python3
"""Build Mente's frozen vendored Codex runtime artifacts.

This is a thin wrapper around the vendored upstream staging helper so release
automation can produce a Mente-owned runtime artifact contract without
reimplementing upstream packaging logic.
"""

from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path
import tempfile


def _load_upstream_artifact_helper():
    helper_path = (
        Path(__file__).resolve().parents[1]
        / "kernel/codex/upstream/sdk/python/scripts/update_sdk_artifacts.py"
    )
    spec = importlib.util.spec_from_file_location(
        "mente_upstream_update_sdk_artifacts",
        helper_path,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load upstream artifact helper from {helper_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def build_runtime_artifact(
    output_dir: Path,
    codex_version: str | None = None,
    platform_tag: str | None = None,
) -> Path:
    """Stage a frozen runtime artifact into ``output_dir`` and return it."""

    helper = _load_upstream_artifact_helper()
    version = codex_version or helper.current_sdk_version()
    output_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="mente-codex-runtime-") as td:
        staging_dir = Path(td) / "runtime"
        helper.stage_python_runtime_package(
            staging_dir=staging_dir,
            codex_version=version,
            binary_path=helper.python_runtime_root()
            / "src"
            / "codex_cli_bin"
            / "bin"
            / helper.runtime_binary_name(),
            platform_tag=platform_tag,
        )
        artifact_dir = output_dir / f"codex-runtime-{version}"
        if artifact_dir.exists():
            if artifact_dir.is_dir():
                import shutil

                shutil.rmtree(artifact_dir)
            else:
                artifact_dir.unlink()
        import shutil

        shutil.copytree(staging_dir, artifact_dir)
    return artifact_dir


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build frozen vendored Codex runtime artifacts for Mente releases"
    )
    parser.add_argument(
        "--output-dir",
        default="dist/runtime-artifacts",
        help="Directory to write staged runtime artifacts into",
    )
    parser.add_argument(
        "--codex-version",
        default=None,
        help="Override the vendored Codex/runtime version to stage",
    )
    parser.add_argument(
        "--platform-tag",
        default=None,
        help="Override the platform tag written into the runtime package metadata",
    )
    args = parser.parse_args(argv)

    artifact_dir = build_runtime_artifact(
        output_dir=Path(args.output_dir),
        codex_version=args.codex_version,
        platform_tag=args.platform_tag,
    )
    print(artifact_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
