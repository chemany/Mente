# Mente C6 Verification And Rollback

**Date:** 2026-04-30

## Required Verification Matrix

A C6 release is shippable only after verifying all of the following:

1. main-path runtime resolution is manifest-driven and release-frozen
2. public `codex` fallback is disabled
3. release artifacts include the vendored `kernel/` slice
4. installer/bootstrap policy writes `.mente-install.json`
5. release installs update by release tag rather than a moving branch head
6. the matching vendored runtime artifact manifest and runtime wheel are
   available for the target release

## Minimum Command Matrix

- `scripts/run_tests.sh` over the C6 bridge/executor/runtime/release/install policy suites
- build verification for sdist/wheel contents
- `python3 -m compileall kernel/codex mente hermes_cli`
- CLI help verification for `scripts/build_mente_codex_runtime_artifacts.py`
  and `scripts/release.py`

## Rollback Inputs

Rollback is defined in terms of frozen Mente release artifacts, not by
re-enabling public `codex`. Operators must retain:

- the prior release id
- the prior runtime artifact manifest
- the prior runtime wheel or equivalent vendored runtime artifact
- the prior `.mente-install.json` values

## Rollback Boundaries

### Normal rollback

Revert to the prior release id and restore the prior runtime artifact manifest
and matching runtime wheel for that release.

### Break-glass runtime override

`MENTE_CODEX_RUNTIME_BIN` may be used only as a temporary operator override for:

- rollback drills
- release validation
- emergency recovery while a correct frozen artifact is restored

It does **not** re-enable ambient public `codex` fallback and must not become a
permanent release policy.

## Failure Handling

If the expected vendored runtime artifact is absent, the runtime must fail
closed with a `runtime_not_bootstrapped`-style error and a message that public
`codex` fallback is disabled.
