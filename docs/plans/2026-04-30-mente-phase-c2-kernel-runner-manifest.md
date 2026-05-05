# Phase C2 Kernel Runner Manifest

## Vendored now

This slice vendors runner + CLI transport backend + result normalization into `kernel/codex/`.
The vendored kernel-owned surface now includes:

- runtime/session protocol
- launcher
- sandbox workspace helpers
- runner
- CLI transport backend
- result normalization

CodexKernelAdapter remains the only upper-layer handoff seam.

## Stays in `mente/`

The following stays in `mente/`:

- runtime config resolution
- private runtime home
- bridge-tool policy
- memory
- cron
- gateway
- orchestrator

## Deferred

Deferred work remains outside C2:

- real sessionful execution path
- native tool dispatch surfaces
- plugins
- skills
- public front-door replacement
- tools vendoring breadth

## Temporary transport note

The public `codex` CLI is still a temporary backend transport only. It is not the control plane.
