# Mente Phase 2 Implementation Plan

> Scope of this slice: convert `gateway` and `cron` ingress into `Task` producers behind env-gated bridges, while preserving existing outer behavior by default.

## Goal

Phase 2 starts the runtime migration for long-lived Hermes surfaces without forcing a full cutover. The immediate objective is narrow:

- `cron.scheduler.run_job()` can emit and execute a normalized `Task`
- `GatewayRunner._run_agent()` can emit and execute a normalized `Task`
- legacy Hermes behavior remains the default when the Mente gates are unset

This keeps the migration reversible and lets us validate the task envelope at the real ingress seams before memory, planning, or richer executor state is layered in.

## Implementation Slice

### 1. Add a thin Hermes bridge in `mente`

Create `mente.integrations.hermes` with:

- `build_cron_task(...)`
- `run_cron_task(...)`
- `build_gateway_task(...)`
- `run_gateway_task(...)`

The bridge owns:

- workspace resolution
- deterministic history serialization for gateway turns
- stable task metadata for cron / gateway provenance
- default `Orchestrator + ContextBuilder + CodexExecutor` wiring

### 2. Route cron through the bridge behind a gate

Add:

- `HERMES_CRON_EXECUTOR=mente`

When enabled, `run_job()` should:

- keep existing prompt construction, session setup, workdir handling, and cleanup
- call `_run_mente_cron_job(...)`
- adapt `ExecutionResult` back into the existing `(success, output, final_response, error)` tuple

When unset, existing `AIAgent` behavior must remain unchanged.

### 3. Route gateway through the bridge behind a gate

Add:

- `HERMES_GATEWAY_EXECUTOR=mente`

When enabled, `_run_agent()` should:

- preserve proxy mode precedence
- execute the Mente bridge in a worker thread
- adapt `ExecutionResult` back into the current gateway result dict

When unset, the current gateway agent path remains unchanged.

## Verification

This slice is complete when:

- cron Mente bridge routing has a dedicated regression test
- gateway Mente bridge routing has a dedicated regression test
- existing Phase 1 tests still pass
- representative cron / gateway legacy-path tests still pass
- `compileall` succeeds for the touched modules

## Status

Implemented on `2026-04-28`:

- Added `mente.integrations.hermes`
- Added env-gated cron bridge
- Added env-gated gateway bridge
- Added routing tests for both entrypoints
- Replaced bridge-side `InMemoryTaskRepository` with persistent SQLite task storage
- Added bridge persistence tests for cron and gateway task records
- Added repository lifecycle cleanup so per-run SQLite connections are closed

## Next Phase 2 Tasks

1. Start threading memory and plan state into the normalized task envelope instead of stuffing them into legacy prompts.
2. Add richer result adaptation so gateway and cron can surface structured actions, artifacts, and verification data from Mente runs.
3. Decide whether Mente task persistence should stay inside `state.db` or move to a dedicated DB once query patterns and retention policy are clearer.
