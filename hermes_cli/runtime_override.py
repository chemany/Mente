"""Developer/source-checkout runtime override helpers."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from hermes_cli.config import load_release_install_manifest
from kernel.codex.release.runtime import expected_vendored_runtime_binary_path

MENTE_CODEX_RUNTIME_BIN_ENV = "MENTE_CODEX_RUNTIME_BIN"


def resolve_source_checkout_runtime_override(project_root: Path) -> str | None:
    """Return an explicit runtime override for developer/source checkouts only."""
    release_install_manifest = load_release_install_manifest(project_root)
    if (
        isinstance(release_install_manifest, dict)
        and release_install_manifest.get("install_mode") == "release"
    ):
        return None

    expected_runtime = expected_vendored_runtime_binary_path(project_root)
    if expected_runtime.exists():
        return None

    resolved_codex = shutil.which("codex")
    if not resolved_codex:
        return None
    return str(Path(resolved_codex).expanduser())


def apply_source_checkout_runtime_override(project_root: Path) -> str | None:
    """Populate the runtime override env var for source checkouts when needed."""
    if os.getenv(MENTE_CODEX_RUNTIME_BIN_ENV, "").strip():
        return os.environ[MENTE_CODEX_RUNTIME_BIN_ENV]

    runtime_override = resolve_source_checkout_runtime_override(project_root)
    if runtime_override:
        os.environ[MENTE_CODEX_RUNTIME_BIN_ENV] = runtime_override
    return runtime_override
