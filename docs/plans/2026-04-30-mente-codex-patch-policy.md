# Mente Codex Patch Policy

**Date:** 2026-04-30

## Scope

This document defines what counts as an allowed Mente patch to the vendored
Codex runtime after C6 freezes the release/main path.

## Patch Classes

### Same-snapshot Mente patch

A same-snapshot Mente patch keeps the pinned upstream snapshot identifier
unchanged and only adjusts Mente-owned compatibility or release surfaces.

Allowed locations by default:

- `kernel/codex/bridge/`
- `kernel/codex/release/`
- `kernel/codex/runtime/`
- `kernel/codex/patches/`
- outer product/runtime policy in `mente/`

### Upstream snapshot upgrade

Anything that changes the vendored upstream snapshot identifier is **not** a
patch. It is a new upstream snapshot upgrade and must run a new C3/C4/C5/C6
verification pass.

## Default Boundary

- Default: **no edits inside the vendored upstream tree**
- Default upstream path under protection: `kernel/codex/upstream/`
- Public `codex` fallback remains disabled
- `CodexKernelAdapter` remains the only upper-layer seam

## Emergency Exception

A rare emergency edit inside `kernel/codex/upstream/` is allowed only when all
of the following are true:

1. the issue cannot be solved in `kernel/codex/bridge/`, `kernel/codex/release/`,
   `kernel/codex/runtime/`, or `kernel/codex/patches/`
2. the edit is required for import safety, release bootstrap, or a production
   regression that blocks the frozen runtime
3. the edit is recorded in `kernel/codex/upstream/README.mente.md` with file
   path, rationale, release impact, and drop criteria
4. the change remains as small and recognizable as possible

## Release Evidence Required

Before shipping a same-snapshot patch release, Mente must keep auditable
references to:

- prior and new Mente release ids
- the pinned upstream snapshot id
- the capability boundary manifest
- the release-freeze runtime artifact manifest
- verification evidence from the C6 matrix

## Non-goals

- no product logic inside `kernel/codex/upstream/`
- no replacement registry for Codex-native capabilities
- no revival of ambient public `codex` as a main-path dependency
