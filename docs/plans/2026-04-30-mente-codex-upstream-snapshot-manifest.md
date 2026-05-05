# Mente Codex Upstream Snapshot Manifest

**Date:** 2026-04-30

## Snapshot Record

- **Upstream Codex repository source:** `https://github.com/openai/codex`
- **Pinned snapshot identifier:** `8f3c06cc97bbb045fe5790a6388625c0db35af7f`
- **Ingestion date:** `2026-04-30`
- **Local edits inside the vendored snapshot:** not allowed by default; only permitted when strictly necessary for basic import safety, and every such edit must be recorded in `kernel/codex/upstream/README.mente.md`

## Boundary Policy

- The upstream snapshot is the **source of truth** for Codex-core behavior in Phase C3.
- The vendored snapshot under `kernel/codex/upstream/` must stay as **pristine as possible** and remain recognizable as upstream Codex.
- Thin Mente-facing entry surfaces live in `kernel/codex/bridge/`.
- Any future compatibility shims or narrowly scoped patch overlays belong in `kernel/codex/patches/`, not as broad rewrites inside the vendored upstream tree.
- Mente product/runtime concerns continue to live outside the upstream snapshot.

## Relationship To The Controlled Fork Roadmap

This manifest follows `docs/plans/2026-04-30-mente-controlled-codex-fork-roadmap.md`:

- upstream Codex remains the source of truth
- vendored source stays recognizable
- local compatibility changes stay outside the upstream tree unless absolutely necessary
- C3 adds manifesting, vendoring, and a thin bridge scaffold only


## C6 Freeze Carry-Forward

This snapshot remains pinned for the C6 release-freeze boundary. Any future
change to the pinned snapshot identifier is a new upstream snapshot upgrade, not
a same-snapshot patch, and must follow
`docs/plans/2026-04-30-mente-codex-upgrade-policy.md`.
