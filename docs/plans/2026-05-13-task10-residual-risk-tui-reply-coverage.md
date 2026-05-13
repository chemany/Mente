# Task 10 Residual Risk: TUI Reply Coverage

## Context

Task 10 aligned TUI reply rendering with the gateway-side coordinator reply
contract. TUI now routes background-worker follow-up replies through the same
kind of deterministic status renderer and emits accepted acknowledgements via
`thinking.delta`.

## Residual Risk

TUI does not yet have a dedicated reply-focused test slice equivalent to
`tests/gateway/test_gateway_coordinator_replies.py`.

The implementation looks structurally aligned with gateway behavior, and the
shared behavior is plausible from code symmetry, but there is no standalone TUI
test file that explicitly locks:

- accepted acknowledgement wording
- running follow-up wording
- blocked reply wording
- completed reply wording
- deterministic-first behavior when persisted state is sufficient

## Why This Is Not A Task 10 Blocker

- TUI reply wiring is present.
- The underlying persisted-state read path is already connected.
- Gateway reply behavior, which defines the intended phase-1 contract, is
  covered and passing.

This is a parity coverage gap, not a known runtime break.

## Recommended Follow-Up

Add one narrow TUI reply test slice mirroring the gateway reply cases, without
expanding the phase-1 scope beyond the current renderer contract.

## Status

- Severity: Medium
- Scope: TUI-specific regression protection
- Suggested owner phase: Post-Task 10 follow-up
