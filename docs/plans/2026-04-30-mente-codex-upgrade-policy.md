# Mente Codex Upgrade Policy

**Date:** 2026-04-30

## Goal

Freeze one Mente release lineage to one vendored Codex snapshot, one capability
boundary, and one runtime artifact set.

## Upgrade Types

### Same-snapshot Mente release

A same-snapshot Mente release may:

- keep the same upstream snapshot identifier
- ship bridge/runtime/release/install fixes outside `kernel/codex/upstream/`
- rotate frozen runtime artifacts built from the same vendored snapshot when
  packaging/bootstrap changes require it

This path still requires C6 verification before release.

### New upstream snapshot upgrade

A new upstream snapshot upgrade changes the pinned vendored snapshot. It must:

1. refresh the upstream snapshot manifest
2. refresh the cutover/capability/release-freeze manifests as needed
3. rerun a dedicated **C3/C4/C5/C6 re-verification pass**
4. publish a new frozen runtime artifact manifest for the new release

## Update Policy For Installed Users

Release installs are governed by `.mente-install.json` and update by
`git_tag_release`, not by tracking a moving `main` branch.

The update path must move:

- from prior release id → new release id
- from prior runtime artifact manifest → new runtime artifact manifest
- from prior frozen vendored runtime artifact → matching new artifact

## Runtime Bootstrap Policy

- one-click install is `release_pinned`
- runtime bootstrap policy is `artifact_manifest_and_runtime_wheel`
- build wrapper entrypoint: `scripts/build_mente_codex_runtime_artifacts.py`
- break-glass operator override remains `MENTE_CODEX_RUNTIME_BIN`

## Prohibited Upgrade Patterns

- no install-time fetch of arbitrary upstream Codex state
- no main-path fallback to public `codex` on `PATH`
- no bypass around `CodexKernelAdapter`
- no product logic migration into `kernel/codex/upstream/`
