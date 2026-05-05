"""Runtime resolution helpers for the frozen vendored Codex release contract."""

from __future__ import annotations

import os
from pathlib import Path

from .manifest import load_vendored_runtime_manifest

MENTE_CODEX_RUNTIME_BIN_ENV = "MENTE_CODEX_RUNTIME_BIN"


class RuntimeNotBootstrappedError(RuntimeError):
    """Raised when the frozen vendored runtime artifact has not been bootstrapped."""


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def expected_vendored_runtime_binary_path(repo_root: Path | None = None) -> Path:
    """Return the expected artifact path from the current frozen release manifest."""
    resolved_repo_root = repo_root or _repo_root()
    manifest = load_vendored_runtime_manifest(resolved_repo_root)
    return resolved_repo_root / Path(manifest.runtime_relative_path)


def resolve_vendored_runtime_binary(repo_root: Path | None = None) -> Path:
    """Resolve the vendored runtime binary without falling back to ambient public codex."""
    override = os.getenv(MENTE_CODEX_RUNTIME_BIN_ENV, "").strip()
    if override:
        override_path = Path(override).expanduser()
        if override_path.exists():
            return override_path
        raise RuntimeNotBootstrappedError(
            "break-glass runtime override is configured but missing: "
            f"{override_path}. public codex fallback is disabled."
        )

    expected_path = expected_vendored_runtime_binary_path(repo_root)
    if expected_path.exists():
        return expected_path

    raise RuntimeNotBootstrappedError(
        "vendored runtime artifact is not bootstrapped for this Mente release; "
        f"expected {expected_path}. public codex fallback is disabled."
    )
