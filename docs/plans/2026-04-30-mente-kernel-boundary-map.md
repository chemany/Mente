# Mente Kernel Boundary And Ownership Map

**Date:** 2026-04-30
**Phase:** C0
**Scope:** Ownership and migration boundary definition for the controlled Codex fork.

## Boundary Rule

`no product logic in kernel`

The forked kernel exists to provide controlled Codex execution capability. It is
not the place for Mente product behavior, runtime orchestration policy, or
application-facing integrations.

## Ownership Map

### Stays In `mente/`

- `MenteRuntime` orchestration and task state transitions
- memory persistence, promotion, retrieval, and injection
- gateway/API ingress, cron, evaluation, replay, and live acceptance flows
- profile/workspace config ownership and product auth UX
- tool exposure policy, bridge tool registry, and runtime-facing product policy

Rationale: these are product concerns that must stay observable, testable, and
owned by Mente rather than being pushed into a forked execution kernel.

### Moves To `kernel/codex/`

- execution loop and model/tool-call runtime
- session protocol and kernel session state machinery
- native engineering tool implementations and dispatch
- sandbox/runtime behavior needed to execute the kernel in a controlled way

Rationale: these surfaces are intrinsic to the Codex-derived execution kernel
and must be Mente-controlled to retire the public `codex` dependency safely.

### Adapter-Only For Now

- `CodexKernelAdapter` request/result seam
- private runtime home/config resolution handoff
- bridge between Mente tool policy and kernel-native tool exposure
- any compatibility layer still required while the external Codex path remains active

Rationale: these surfaces preserve the Phase B1/B2/B3 architecture until later
Phase C slices finish vendoring the kernel internals they currently shield.

## Runtime Owners

### `MenteRuntime` Ownership

`MenteRuntime` owns:

- task ingestion and normalization
- execution request assembly
- memory and scheduling side effects
- policy decisions for tools, runtime mode, and visibility
- product-facing debugging and observability

### `CodexKernel` Ownership

`CodexKernel` owns:

- execution-turn mechanics
- tool invocation mechanics
- session machinery
- sandboxed engineering runtime behavior
- structured execution-result production

## Bridge Surfaces Between Them

- `ExecutionRequest` into the adapter/kernel boundary
- `ExecutionResult` back into the runtime boundary
- resolved runtime-home/config inputs from Mente into the kernel
- resolved tool exposure policy from Mente into kernel-native capability selection
- structured memory candidates and summaries from kernel back to Mente

## Forbidden Leakage Patterns

- product memory logic in kernel execution code
- cron, gateway, replay, or evaluation logic in `kernel/codex/`
- direct upper-layer imports of kernel internals that bypass the adapter seam
- kernel reads from uncontrolled public Codex config or host-local `agents.md`
- CLI/front-door behavior treated as the canonical product runtime contract

## Migration Invariants For Phase C

- Preserve the Phase A isolation baseline.
- Preserve the Phase B1 adapter seam as the only supported upper-layer execution boundary.
- Preserve the Phase B2 private runtime-home/config ownership model.
- Preserve the Phase B3 tool exposure policy and bridge-surface ownership in `mente/`.
- Keep vendoring slices additive and reversible; no slice should require collapsing MenteRuntime into the kernel.
