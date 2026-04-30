"""Import-safe bridge metadata for Phase C3.

This scaffold defines the narrow Mente-facing handoff surface around the
vendored upstream Codex snapshot without changing the current execution path.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class CodexSnapshotBridgeSurface:
    """Metadata-only description of the C3 bridge boundary."""

    upstream_root: str = "kernel/codex/upstream/"
    bridge_root: str = "kernel/codex/bridge/"
    patch_root: str = "kernel/codex/patches/"
    adapter_seam: str = "CodexKernelAdapter"
    cutover_complete: bool = False
    execution_path_switched: bool = False


def get_codex_handoff_surface() -> CodexSnapshotBridgeSurface:
    """Return the only intended Mente-facing handoff descriptor for C3."""

    return CodexSnapshotBridgeSurface()
