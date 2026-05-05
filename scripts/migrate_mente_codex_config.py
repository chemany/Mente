#!/usr/bin/env python3
"""Migrate legacy private Codex TOML config into the canonical YAML surface."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from kernel.codex.config import migrate_legacy_private_codex_config


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Copy private Codex config from legacy config.toml / codex.toml into "
            "MENTE_HOME/config.yaml and optional workspace .mente/config.yaml."
        )
    )
    parser.add_argument(
        "--workspace",
        action="append",
        default=[],
        help="Workspace root whose .mente/codex.toml should be migrated to .mente/config.yaml.",
    )
    args = parser.parse_args()

    profile_result = migrate_legacy_private_codex_config()
    print(f"profile: {profile_result['profile']}")

    for workspace in args.workspace:
        result = migrate_legacy_private_codex_config(workspace=Path(workspace))
        print(f"workspace {workspace}: {result['workspace']}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
