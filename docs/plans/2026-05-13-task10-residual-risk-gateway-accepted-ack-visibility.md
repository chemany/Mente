# Task 10 Residual Risk: Gateway Accepted Ack Visibility

## Context

Task 10 wired the first coordinator-visible delegated acknowledgement through the
gateway Mente progress channel. The accepted acknowledgement is emitted from the
live worker registration path in `gateway/run.py` rather than from a dedicated
front-door reply surface.

## Residual Risk

There is not yet one focused gateway integration test that proves a real
delegated turn always produces a user-visible accepted acknowledgement through
the live registration -> progress queue path.

Current coverage is strong at the renderer level and narrow wiring level, but
the full delegated ingress path is still inferred from nearby tests rather than
directly locked by one dedicated assertion.

## Why This Is Not A Task 10 Blocker

- The accepted reply renderer exists and is exercised.
- The live worker registration path is wired.
- The reply regression slice is green.

This is therefore a confidence/coverage gap, not an observed behavioral bug.

## Recommended Follow-Up

Add one gateway integration test that:

1. Starts a real delegated Mente gateway turn.
2. Observes the first coordinator-visible acknowledgement.
3. Asserts the acknowledgement includes lane, job id, and next-step language.

## Status

- Severity: Medium
- Scope: Test coverage / user-visible acknowledgement path
- Suggested owner phase: Post-Task 10 or Task 11 follow-up if regression budget allows
