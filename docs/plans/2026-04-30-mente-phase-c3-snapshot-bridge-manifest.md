# Phase C3 Snapshot Bridge Manifest

**Date:** 2026-04-30

## Boundary Locations

- Upstream snapshot location: `kernel/codex/upstream/`
- Thin bridge location: `kernel/codex/bridge/`
- Future patch layer location: `kernel/codex/patches/`

## Ownership Rule

- `kernel/codex/bridge/` is the **only allowed Mente-facing call surface** into the vendored snapshot during Phase C3.
- `kernel/codex/upstream/` remains upstream-owned source and should stay recognizable.
- `kernel/codex/patches/` is reserved for minimal, auditable compatibility overlays if they become necessary later.

## Cutover Status

- The **main execution path is unchanged** in C3.
- The vendored snapshot is present, but the **cutover has not happened yet**.
- `CodexKernelAdapter` remains the upper-layer handoff seam.
- C3 adds metadata and import-safe bridge scaffolding only; it does not switch `CodexExecutor` to a new main call chain.
