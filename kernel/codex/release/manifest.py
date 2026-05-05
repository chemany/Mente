"""Mente-owned frozen release manifest for vendored Codex runtime resolution."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import platform


def _normalize_system(value: str) -> str:
    lowered = value.strip().lower()
    if lowered == "darwin":
        return "macos"
    if lowered.startswith("win"):
        return "windows"
    return lowered


def _normalize_machine(value: str) -> str:
    lowered = value.strip().lower()
    if lowered in {"x86_64", "amd64"}:
        return "x86_64"
    if lowered in {"aarch64", "arm64"}:
        return "arm64"
    return lowered or "unknown"


def current_platform_tag() -> str:
    """Return the platform tag used by the frozen vendored runtime layout."""
    return f"{_normalize_system(platform.system())}-{_normalize_machine(platform.machine())}"


def current_runtime_binary_name() -> str:
    """Return the expected runtime executable name for this platform."""
    return "codex.exe" if _normalize_system(platform.system()) == "windows" else "codex"


@dataclass(frozen=True)
class VendoredCodexReleaseManifest:
    """Minimal machine-readable runtime contract pinned by a Mente release."""

    mente_release: str
    upstream_snapshot: str
    capability_manifest: str
    cutover_manifest: str
    release_freeze_manifest: str
    runtime_platform_tag: str
    runtime_relative_path: str
    public_codex_fallback_allowed: bool = False


def load_vendored_runtime_manifest(repo_root: Path | None = None) -> VendoredCodexReleaseManifest:
    """Load the frozen vendored runtime contract for the current Mente release."""
    _ = repo_root  # reserved for future file-backed manifest loading
    runtime_relative_path = (
        Path("kernel")
        / "codex"
        / "release"
        / "artifacts"
        / current_platform_tag()
        / current_runtime_binary_name()
    )
    return VendoredCodexReleaseManifest(
        mente_release="0.11.0",
        upstream_snapshot="8f3c06cc97bbb045fe5790a6388625c0db35af7f",
        capability_manifest="docs/plans/2026-04-30-mente-phase-c5-capability-boundary-manifest.md",
        cutover_manifest="docs/plans/2026-04-30-mente-phase-c4-cutover-manifest.md",
        release_freeze_manifest="docs/plans/2026-04-30-mente-codex-release-freeze-manifest.md",
        runtime_platform_tag=current_platform_tag(),
        runtime_relative_path=runtime_relative_path.as_posix(),
    )
