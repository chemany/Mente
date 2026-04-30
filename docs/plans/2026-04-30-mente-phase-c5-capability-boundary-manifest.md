# Phase C5 Capability Boundary Manifest

## Status

- vendored Codex native capability surface is active
- CodexKernelAdapter remains the only upper-layer handoff seam
- Mente now filters vendored native capability from the outside instead of defining a replacement registry

## Active vendored capability surface

The active source-of-truth surface is the vendored upstream snapshot exposed through:

- `kernel/codex/upstream/codex-rs/tools/src/lib.rs`
- `kernel/codex/upstream/codex-rs/plugin/src/lib.rs`
- `kernel/codex/upstream/codex-rs/skills/src/lib.rs`
- `kernel/codex/upstream/sdk/python/src/codex_app_server/`

`kernel/codex/bridge/tool_surface.py` is only a bridge-owned map of those vendored surfaces. It does not replace the vendored registry and does not move product logic into `kernel/codex/upstream/`.

## Ownership split

### Codex-owned capability

- plugin hooks belong to Codex
- skill loading hooks belong to Codex
- native tools belong to vendored Codex
- Python app-server touchpoints remain vendored Codex SDK surface

### Mente-owned capability

- mente bridge tools remain outside kernel
- task ingress policy remains in `mente/`
- product integration remains in `mente/`
- runtime orchestration, gateway wiring, memory integration, and product-specific enablement remain Mente responsibilities

## Bridge-tool boundary

Mente bridge tools remain product-owned in `mente/executors/bridge_tools.py` and are attached separately from vendored native capability. They are not merged into vendored Codex native discovery and are not added to `kernel/codex/upstream/`.

## C5 freeze

What is frozen at the end of C5:

- vendored native capability is the source of truth
- Mente policy operates as an outer filter over vendored native tools
- bridge tools remain distinct from vendored native tools
- plugin/skill hooks stay Codex-owned
- product integration remains in `mente/`
- the C4 front-door cutover and the adapter seam remain unchanged

## Deferred

Still deferred beyond this boundary freeze:

- any attempt to move Mente bridge tools into vendored Codex registries
- product-specific plugin behavior inside `kernel/codex/upstream/`
- product-specific skill behavior inside `kernel/codex/upstream/`
- broader app-server product workflow adoption beyond the mapped touchpoints
