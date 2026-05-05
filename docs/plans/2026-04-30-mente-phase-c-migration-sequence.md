# Phase C Migration Sequence

**Date:** 2026-04-30
**Phase:** C0 output for Phase C execution
**Scope:** Tactical vendoring order for the controlled Codex fork

## Goal

Define a slice-by-slice migration path that vendors only the Codex kernel
surfaces Mente actually needs, while preserving the Phase A / B1 / B2 / B3
architecture constraints already in place.

## Ingestion Order

1. `runtime/` execution loop skeleton required by `CodexKernelAdapter`
2. `session/` protocol and stateless-vs-session execution machinery
3. `sandbox/` runtime control and explicit isolation behavior
4. `tools/` native engineering tool dispatch and schema surfaces
5. selective plugin-loading mechanics that are strictly required by vendored tools
6. selective skill-loading mechanics only after kernel execution parity is stable

This order intentionally vendors the kernel core before plugin breadth, skill
breadth, or any public CLI/front-door surface.

## First Vendoring Slice

The `first vendoring slice` should ingest only the smallest kernel surfaces
needed to replace the shell-out path without collapsing product boundaries:

- candidate directories first:
  - `runtime/`
  - `session/`
  - the minimum `sandbox/` helpers required to execute the vendored loop
- explicit exclusions:
  - plugin catalogs
  - skill packs
  - CLI/front-door code
  - product-facing config, gateway, memory, cron, and evaluation logic

The objective of the first slice is to let Mente execute through a vendored
kernel core while Phase B1/B2/B3 seams still enforce runtime ownership.

## External Until Later

These surfaces should remain external or adapter-owned until later Phase C work:

- full plugin discovery breadth
- full skill corpus and user-facing skill management
- public Codex CLI/front-door behavior
- product config/auth resolution
- Mente bridge tool policy and runtime-owned integrations

## Validation Gates After Each Slice

`validation gates after each slice`:

1. `scripts/run_tests.sh tests/mente/test_kernel_inventory.py -v`
2. targeted executor/integration suites for the affected kernel boundary:
   - `tests/mente/test_kernel_adapter.py`
   - `tests/mente/test_codex_executor.py`
   - `tests/mente/test_hermes_integration.py`
   - `tests/mente/test_tool_policy.py`
   - `tests/mente/test_bridge_tools.py`
3. `uv run python -m compileall mente/executors mente/integrations mente/orchestrator mente/task_core`
4. confirm no new dependency from upper layers onto vendored kernel internals beyond the adapter seam
5. confirm no slice reintroduces public `codex` runtime-home/config leakage

## Rollback Boundary

`rollback boundary`:

- each slice must land as an isolated commit range that can be reverted without undoing earlier verified slices
- if a slice destabilizes runtime behavior, revert only that slice and restore the last green adapter-backed boundary
- do not partially retain vendored code that forces upper layers to bypass `CodexKernelAdapter`
- do not continue to the next slice until tests and compile verification return to green

## Public `codex` Retirement Point

The public `codex` dependency can be retired from the main path only after:

- the vendored runtime/session/sandbox/tool path is green under Mente integration tests
- upper-layer execution no longer shells out through the current external adapter path
- Phase A isolation and Phase B2 private runtime ownership still hold
- Phase B3 tool exposure policy still governs capability visibility

Until then, the external path remains a fallback boundary, not a design target.
