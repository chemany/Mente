#!/usr/bin/env python3
"""Build the runtime source bundle shipped inside the npm bootstrapper."""

from __future__ import annotations

import subprocess
import tarfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
BUNDLE_PATH = REPO_ROOT / "npm" / "installer" / "bundles" / "mente-runtime-source.tar.gz"
ARC_PREFIX = "mente-agent"
EXCLUDED_PREFIXES = (
    "npm/installer/bundles/",
)


def iter_tracked_files() -> list[str]:
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
    )
    tracked = []
    for raw_path in result.stdout.decode("utf-8").split("\0"):
        rel_path = raw_path.strip()
        if not rel_path:
            continue
        if any(rel_path.startswith(prefix) for prefix in EXCLUDED_PREFIXES):
            continue
        tracked.append(rel_path)
    return tracked


def build_bundle() -> None:
    tracked_files = iter_tracked_files()
    BUNDLE_PATH.parent.mkdir(parents=True, exist_ok=True)

    with tarfile.open(BUNDLE_PATH, "w:gz", format=tarfile.PAX_FORMAT) as archive:
        for rel_path in tracked_files:
            source_path = REPO_ROOT / rel_path
            if not source_path.exists():
                continue
            archive.add(source_path, arcname=f"{ARC_PREFIX}/{rel_path}")

    print(f"Built npm runtime source bundle: {BUNDLE_PATH.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    build_bundle()
