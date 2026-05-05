# Mente Codex Release Freeze Manifest

**Date:** 2026-04-30

## Release Freeze Intent

This manifest records the starting baseline for the C6 release freeze. Its role
is to bind one Mente release lineage to one vendored Codex snapshot, one
capability boundary, one allowed patch boundary, and one installer/bootstrap
policy before runtime behavior changes land.

## Frozen Inputs

- pinned upstream snapshot identifier: `8f3c06cc97bbb045fe5790a6388625c0db35af7f`
- c3 snapshot inventory reference: `docs/plans/2026-04-30-mente-codex-upstream-snapshot-manifest.md`
- phase c4 cutover manifest reference: `docs/plans/2026-04-30-mente-phase-c4-cutover-manifest.md`
- phase c5 capability boundary manifest reference: `docs/plans/2026-04-30-mente-phase-c5-capability-boundary-manifest.md`
- adapter seam remains: `CodexKernelAdapter`

## Current Runtime Binary Path Gap

The current bridge still selects a vendored runtime binary path under:

- `kernel/codex/upstream/sdk/python-runtime/src/codex_cli_bin/bin/codex`

That path reflects upstream runtime packaging layout assumptions, but it is not
yet a Mente-owned release artifact contract and the binary is not present in the
vendored source tree. This runtime binary path gap must be replaced in C6 by a
frozen manifest-driven runtime locator with explicit bootstrap/install policy.

## Current Packaging/Install Gap

The current packaging/install gap is:

- release packaging metadata does not yet include the `kernel/` slice
- `MANIFEST.in` does not yet graft `kernel/`
- source checkout and moving-branch workflows still exist beside the desired
  release-pinned installation path

C6 must close this packaging/install gap by shipping the vendored kernel slice,
publishing release-frozen runtime artifacts, and defining one-click bootstrap
and update behavior per Mente release.

## Patch Boundary Reuse

Existing reusable freeze inputs for C6:

- snapshot boundary: `docs/plans/2026-04-30-mente-codex-upstream-snapshot-manifest.md`
- capability boundary: `docs/plans/2026-04-30-mente-phase-c5-capability-boundary-manifest.md`
- patch boundary location: `kernel/codex/patches/`
- upstream local-edit ledger: `kernel/codex/upstream/README.mente.md`

## Runtime Artifact Manifest Contract

The C6 artifact manifest is machine-readable and installer-oriented:

- artifact manifest path: `dist/codex-runtime/mente-codex-runtime-artifact-manifest.json`
- required fields: mente release, upstream snapshot, codex version, platform tag, artifact filename, sha256
- build wrapper entrypoint: `scripts/build_mente_codex_runtime_artifacts.py`
- upstream staging helper reused by the wrapper: `kernel/codex/upstream/sdk/python/scripts/update_sdk_artifacts.py`

The wrapper must reuse vendored upstream staging behavior for the runtime wheel
and only add Mente-owned release-freeze metadata around it.

## C6 Exit Condition

The C6 release freeze is complete only when:

- the public `codex` binary is retired from the main path
- vendored runtime resolution is manifest-driven and release-pinned
- upgrade and patch policy are explicit per Mente release
- one-click installation bootstraps the matching frozen vendored runtime
- rollback remains possible at the release-manifest boundary
