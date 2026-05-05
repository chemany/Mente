# Phase C4 Cutover Manifest

## Status

- Vendored Codex bridge is now the main execution path.
- CodexKernelAdapter remains the only upper-layer handoff seam.
- The user-environment public `codex` binary no longer defines the architectural control plane.
- Selected front door: vendored runtime binary.
- The bridge owns vendored bootstrap metadata, vendored command construction, and vendored front-door invocation.

## Boundary

What moved into the bridge/kernel path:

- vendored bootstrap contract in `kernel/codex/bridge/entrypoints.py`
- bridge-selected vendored front-door command construction
- runner delegation through the bridge-owned front door
- executor cutover to the bridge while preserving the adapter-only surface

What stays in `mente/`:

- runtime config resolution
- auth seeding into the private runtime home
- product-facing orchestration and integration wiring

## Deferred

Tools/plugins/skills migration remains deferred.

Deferred items for post-C4:

- tools
- plugins
- skills
- real sessionful execution path
- app-server front-door exploration beyond the selected front door

## Notes

The selected front door for C4 is the vendored runtime binary path described by the vendored python runtime locator policy. This keeps a process boundary without relying on ambient public binary discovery as the main control surface.


## C6 Carry-Forward

C6 keeps the C4 seam unchanged: `CodexKernelAdapter` remains the only
upper-layer seam and the selected front door stays vendored. Release installs
and rollback drills must not revive ambient public `codex` as a control-plane
dependency.
