# Phase C1 Kernel Slice Manifest

**Date:** 2026-04-30
**Phase:** C1
**Status:** first real vendoring slice only

## Vendored Now

The C1 slice vendors only the minimum kernel-owned execution spine under `kernel/codex/`:

- runtime protocol
- minimal session protocol
- launcher
- sandbox workspace helpers

The public `codex` CLI is still the transport backend for now. C1 does not
turn the public CLI into the architectural control plane.

## Stays In `mente/`

The following concerns stay in `mente/` and continue to flow through the
`CodexKernelAdapter` seam:

- runtime config resolution
- private runtime home ownership
- bridge-tool policy
- memory
- cron
- gateway

## Deferred

The following areas are intentionally deferred to later Phase C slices:

- full session machinery
- native tool ingestion breadth
- plugins
- skills
- public CLI front-door replacement

## Boundary Rule

This slice vendors kernel execution helpers only. Product logic stays outside
the kernel, and upper layers continue to call the adapter seam rather than
import `kernel/codex/` directly.
