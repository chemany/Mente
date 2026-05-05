# Mente Codex Fork Ingestion Inventory

**Date:** 2026-04-30
**Phase:** C0
**Scope:** Inventory only. No vendoring, runtime rewiring, or product-boundary expansion.

## Purpose

This document records which Codex capability surfaces Mente must eventually ingest
into a controlled fork, which ones should stay outside the fork for now, and which
ones should not be pulled into the kernel at all.

The inventory assumes the architectural constraints already established in:

- [Mente Codex-Native Runtime Design](./2026-04-29-mente-codex-native-runtime-design.md)
- Phase A execution isolation hardening
- Phase B1 adapter seam extraction
- Phase B2 private runtime home and config ownership
- Phase B3 tool exposure policy and bridge-surface ownership

## Classification Legend

- `must-ingest`: kernel capability required for a controlled internal Codex execution path
- `defer`: related surface exists, but should stay external or adapter-owned until a later slice
- `do-not-ingest`: product-layer or host-integration logic that must remain outside `kernel/codex/`

## Inventory

### Runtime / Execution Loop

- Classification: `must-ingest`
- Purpose: Core model turn loop, tool-call orchestration, structured assistant-result production.
- Why Mente needs it: A controlled fork must own the executor semantics instead of trusting a public `codex` binary.
- Expected target location: `kernel/codex/runtime/`
- Coupling/risk notes: Preserve the Phase B1 `CodexKernelAdapter` seam; do not let orchestrator or gateway layers depend on kernel internals directly.

### Session Protocol

- Classification: `must-ingest`
- Purpose: Session lifecycle, message/state protocol, and stable structured response contract.
- Why Mente needs it: Long-lived kernel sessions and stateless task mode both require a Mente-owned protocol rather than public Codex session behavior.
- Expected target location: `kernel/codex/session/`
- Coupling/risk notes: Session semantics must remain behind adapter-owned request/result contracts so Phase A and B2 isolation guarantees are not bypassed.

### Tools

- Classification: `must-ingest`
- Purpose: Native engineering tools, tool dispatch, and schema exposure for kernel execution.
- Why Mente needs it: Mente needs the kernel-native tool surface without inheriting uncontrolled host defaults.
- Expected target location: `kernel/codex/tools/`
- Coupling/risk notes: Tool exposure policy stays owned by Mente; only the native tool implementation layer belongs in the kernel.

### Plugins

- Classification: `defer`
- Purpose: Extensible capability loading and lifecycle hooks around the kernel tool/runtime surface.
- Why Mente needs it or does not need it: Some plugin mechanics may eventually be required for parity, but C1 should not ingest plugin breadth before the base kernel loop is under control.
- Expected target location: Later candidate for `kernel/codex/plugins/`; remain external for C0/C1 planning.
- Coupling/risk notes: High coupling to tool loading, config, and environment assumptions; ingest only after runtime/session/tool kernel slices are stable.

### Skills

- Classification: `defer`
- Purpose: Task guidance and prompt-packaged workflow assets used by engineering flows.
- Why Mente needs it or does not need it: Skill loading matters for Codex-native behavior, but the first controlled fork slices can proceed without vendoring the full skill corpus.
- Expected target location: Later candidate for `kernel/codex/skills/`
- Coupling/risk notes: Keep Mente runtime skills and policy-owned exposure outside the kernel; only kernel engineering skill mechanics are candidates for later ingestion.

### Sandbox/Runtime

- Classification: `must-ingest`
- Purpose: Sandbox policy, subprocess/runtime environment control, and execution isolation defaults.
- Why Mente needs it: The controlled fork must preserve Phase A and B2 guarantees that execution ignores uncontrolled public Codex state.
- Expected target location: `kernel/codex/sandbox/`
- Coupling/risk notes: Any ingestion must preserve Mente-owned runtime home and explicit config layering rather than reintroducing public host leakage.

### Config/Auth Surface

- Classification: `defer`
- Purpose: Provider configuration, auth resolution, and runtime settings consumed by the kernel.
- Why Mente needs it or does not need it: The kernel needs a narrow config/auth interface, but ownership of config resolution remains in Mente from Phase B2.
- Expected target location: Minimal kernel-facing config reader may later live under `kernel/codex/runtime/`; full config ownership stays outside.
- Coupling/risk notes: Do not ingest user-facing profile config, workspace overlay logic, or product auth UX into the kernel.

### CLI/Front-Door Surface

- Classification: `do-not-ingest`
- Purpose: Public entrypoints, shell UX, argument parsing, and product-facing invocation flows.
- Why Mente needs it or does not need it: Mente should consume the kernel through adapter/runtime integration, not by inheriting public CLI behavior as the main control plane.
- Expected target location: Stay outside `kernel/codex/`; Mente-facing product entrypoints remain in `mente/` and existing app surfaces.
- Coupling/risk notes: Pulling CLI/front-door concerns into the kernel would collapse the MenteRuntime vs CodexKernel boundary.

## Immediate C1 Handoff

The first vendoring slice should start from the `must-ingest` surfaces with the
lowest product-boundary spill risk:

1. `runtime / execution loop`
2. `session protocol`
3. `sandbox/runtime`
4. `tools`

The inventory deliberately does not authorize movement of plugin breadth,
skill packs, or product entrypoints in C0.
