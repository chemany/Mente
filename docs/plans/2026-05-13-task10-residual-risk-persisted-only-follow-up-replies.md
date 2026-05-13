# Task 10 Residual Risk: Persisted-Only Follow-Up Replies

## Context

Task 10 improved coordinator-visible replies by merging live background worker
registry data with persisted worker job state. Frontdesk follow-up entry points
in both gateway and TUI still begin by locating the current in-memory worker job
handle, then enrich that payload from persisted state.

## Residual Risk

There is not yet a focused guarantee that a follow-up reply still works when the
live registry entry is gone but persisted worker job state remains readable.

Examples:

- process restart after worker completion
- registry eviction while `mente_session_jobs` still has the latest checkpoint
- user asks for results after the in-memory handle is gone but before the
  session-level context is rebuilt

The current Task 10 implementation primarily proves "live registry + persisted
state" rather than "persisted state alone is sufficient."

## Why This Is Not A Task 10 Blocker

- The phase-1 plan did not require a new durable lookup state machine.
- Current flows work when the live job handle still exists, which is the common
  path covered by the new tests.
- No direct failure was observed in the reviewed slice.

This is a resilience gap around registry loss / restart scenarios.

## Recommended Follow-Up

Add one focused fallback read path and test that:

1. Finds the most relevant persisted worker job when no active in-memory worker
   handle exists.
2. Returns a deterministic completed/blocked/result reply without reopening the
   worker runtime context.

## Status

- Severity: Medium
- Scope: Restart resilience / persisted-state-only follow-up
- Suggested owner phase: Follow-up after Task 11 or later hardening pass
