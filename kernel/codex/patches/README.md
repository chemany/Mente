# Mente Codex Patch Boundary

This directory is the default landing zone for **Mente-authored Codex patch overlays**
outside the vendored upstream snapshot.

## Default Rule

- Prefer compatibility work in `kernel/codex/bridge/`, `kernel/codex/release/`,
  `kernel/codex/runtime/`, or this `kernel/codex/patches/` root.
- Do **not** edit `kernel/codex/upstream/` by default.
- If an emergency upstream-tree edit is unavoidable, record the file path,
  rationale, release impact, and drop criteria in
  `kernel/codex/upstream/README.mente.md`.

## What Belongs Here

- release-freeze compatibility shims
- small patch overlays that adapt vendored Codex behavior to Mente-owned
  runtime/bootstrap contracts
- narrowly scoped fixes that can be removed on the next upstream snapshot

## What Does Not Belong Here

- product logic
- policy/orchestration that belongs in `mente/`
- long-lived forks of vendored upstream subsystems

## Verification Requirement

Every patch added here must be tied to:

- a specific Mente release
- a specific upstream snapshot
- passing C4/C5/C6 verification evidence
- an explicit removal or rollover plan for the next upgrade
