# Mente Codex-Native Runtime Design

**Date:** 2026-04-29

**Product Definition:** `Mente = Codex-native programmable assistant runtime`

## Goal

Turn Mente from a task/memory layer that shells out to a public `codex` CLI into a self-contained product with a controlled Codex-derived execution kernel.

The target state is:

- users install `Mente`, not a public `codex` binary
- Mente owns runtime isolation, memory, orchestration, cron, multi-channel ingress, debug surfaces, and evaluation
- a forked Codex kernel provides the core engineering execution, tools, plugins, skills, and sandbox/runtime behavior
- upstream Codex releases do not silently change Mente behavior

## Why This Direction

The current external-CLI model has structural problems:

- public Codex runtime can read user-local config, rules, and `agents.md`
- CLI flags and behaviors drift across releases
- installation depends on a separately managed external toolchain
- Mente cannot fully guarantee reproducibility or isolation

At the same time, Codex is materially stronger than the current Hermes/OpenClaw-style execution core. The value is not only the final executor loop, but also the broader tool/runtime/plugin capability surface.

The design goal is therefore not "replace Codex", but "make Codex capability an internal kernel of Mente under controlled product ownership".

## Product Boundary

Mente should be designed as two explicit layers:

- `CodexKernel`
- `MenteRuntime`

`CodexKernel` is a controlled fork of Codex that provides:

- model interaction
- tool calling
- plugin and skill loading
- sandbox/runtime behavior
- execution loop
- session protocol
- structured final output contract

`MenteRuntime` provides:

- task ingestion and normalization
- task state machine and orchestration
- memory persistence, promotion, retrieval, and injection
- cron and scheduled jobs
- gateway and API server ingress
- evaluation, replay, benchmark, and live acceptance tooling
- debug and visualization surfaces

This is intentionally not "Mente as a thin Codex wrapper". It is "Codex as the execution kernel, Mente as the runtime and product layer".

## Recommended Fork Strategy

Adopt a controlled full fork.

That means:

- fork and vendor the Codex kernel code into the Mente repo
- freeze kernel behavior per Mente release
- stop depending on the public `codex` binary for normal product operation
- keep a clean boundary so Mente logic does not sprawl through the kernel tree

This is not a "track upstream forever" strategy. It is a "selectively absorb upstream snapshots only when Mente chooses to" strategy.

## Repository Structure

Use a single repository with explicit logical boundaries:

- `kernel/codex/`
- `mente/`
- existing app and ingress layers

Recommended shape:

```text
kernel/
  codex/
    runtime/
    tools/
    plugins/
    skills/
    session/
    sandbox/
    cli/

mente/
  executors/
  orchestrator/
  task_core/
  memory/
  integrations/
  testing/
  gateway_bridge/
  cron_bridge/

gateway/
hermes_cli/
web/
docs/plans/
```

Rules:

- product-specific logic belongs in `mente/`
- kernel-specific logic belongs in `kernel/codex/`
- only execution-kernel-required changes should modify the forked kernel
- memory, cron, gateway, and eval logic should not be pushed down into the kernel

## Runtime Interface

The current `CodexExecutor` shell-out model is transitional. The target interface is a stable adapter:

- `CodexKernelAdapter`

CodexKernelAdapter is the supported handoff point for the future controlled fork.

The Mente orchestrator should only depend on structured contracts:

- `ExecutionRequest`
- `ExecutionResult`

The orchestrator should not know about:

- CLI flags
- temp schema files
- user config paths
- public `codex` session behavior

Upper layers should not grow new direct dependencies on CLI-specific details.

The adapter becomes responsible for:

- request translation into kernel calls
- structured output parsing
- session lifecycle control
- tool policy application
- isolation defaults
- resolved private runtime ownership inputs from Mente

In the transitional external-CLI phase, this means Mente should resolve the
private runtime home and merged config model before adapter execution, then
pass that explicit runtime ownership into the executor instead of relying on
public `~/.codex` state at execution time.

Recommended modes:

- `stateless_task_mode`
- `kernel_session_mode`

`stateless_task_mode` is the default for reproducible orchestration, replay, benchmark, and most API-driven execution.

`kernel_session_mode` is for long-lived coding workbench flows, but must still be explicitly created and owned by Mente, not inherited from user-local Codex state.

## Memory Model

CodexKernel should remain stateless by default.

Mente owns memory through:

- `MemoryRepository`
- `MemoryPromoter`
- `ContextBuilder`
- policy-driven retrieval and injection

CodexKernel returns structured outputs, including:

- `assistant_summary`
- `memory_candidates`

Mente then decides:

- what to promote
- what scope to assign
- what to inject next turn
- how much prompt budget to spend

This keeps memory observable, testable, replayable, and independent of hidden kernel state.

## Tools, Plugins, and Skills

Preserve Codex-native capability, but move exposure control to Mente.

Design three layers:

- `Kernel Native Tools`
- `Mente Bridge Tools`
- `Policy Filter Layer`

`Kernel Native Tools` include native engineering tools such as file operations, shell, patching, search, and plugin-provided capabilities.

`Mente Bridge Tools` expose runtime-owned assistant capabilities, such as:

- `mente_memory_query`
- `mente_memory_append`
- `mente_task_lookup`
- `mente_schedule_cron`
- `mente_gateway_send`
- `mente_session_notify`

`Policy Filter Layer` is built by Mente for each task using:

- task type
- ingress source
- workspace
- allowed tool set
- user or tenant policy
- budget and safety constraints

Skills should also split into:

- kernel engineering skills
- Mente runtime skills

This preserves Codex capability without allowing uncontrolled environment-driven tool exposure.

## Isolation Principles

Isolation must be a product default, not a best-effort flag.

The kernel runtime should, by default:

- ignore public user config
- ignore uncontrolled rules files
- avoid inheriting public `agents.md`
- use a private Mente-managed runtime home
- run with explicit sandbox mode and policy

Any user/project customization should become explicit Mente-managed profiles or workspace overlays, not implicit leakage from the host environment.

This is required to solve the isolation failure already observed in live testing.

## Config Model

Use a three-layer configuration system:

- `system defaults`
- `profile config`
- `workspace overlay`

`system defaults` ship with Mente and define kernel/runtime defaults.

`profile config` contains user-selected settings such as providers, auth, language defaults, dashboard settings, and safe runtime preferences.

`workspace overlay` can tune task and tool behavior per project, but should not freely mutate kernel-global behavior.

The configuration entrypoint should be unified under Mente. Users should not need to maintain separate Codex config for normal product operation.

## Installation and Distribution

The user installs `Mente`, not public Codex.

Recommended product entrypoints:

- `mente`
- `mente setup`
- `mente doctor`

User experience target:

1. install one package
2. run `mente setup`
3. configure provider/auth once
4. use gateway, dashboard, cron, and coding runtime immediately

The packaged product should include:

- the controlled Codex kernel
- Mente runtime
- default config
- evaluation and diagnostics tooling

## Versioning and Upgrade Policy

Do not auto-follow upstream Codex.

Instead:

- each Mente release binds to a fixed Codex kernel snapshot
- kernel upgrades happen only when explicitly chosen
- every upgrade runs replay, benchmark, live eval, and isolation suites

This avoids silent compatibility drift and lets Mente own release quality.

## Implementation Roadmap

### Phase A: Execution Isolation Hardening

Goal:

- stabilize the current external Codex path enough to create a trustworthy baseline

Scope:

- enforce private runtime isolation for the current executor path
- add isolation validation and regression tests
- keep memory loop and live eval green

Why first:

- current live testing proves memory loop works
- current live testing also proves session isolation is still vulnerable
- this phase defines the runtime guarantees that the future kernel fork must preserve

### Phase B: Kernel Adapter Extraction

Goal:

- remove upper-layer dependence on CLI details

Scope:

- introduce `CodexKernelAdapter`
- keep `ExecutionRequest` and `ExecutionResult` as the only upper-layer contract
- centralize structured output, session control, and tool policy

Why second:

- this creates the seam that allows shell-out to be replaced by embedded kernel calls

### Phase C: Controlled Full Fork

Goal:

- vendor Codex kernel into `kernel/codex/` and make Mente self-contained

Scope:

- bring in kernel runtime, tools, plugins, and skill system
- replace external `codex` dependency in the main product path
- make Mente bridge tools first-class kernel tools

Why third:

- after Phase B, the product layer no longer depends on public CLI shape
- this makes the fork materially safer

### Phase D: Product Hardening

Goal:

- make the forked runtime installable, diagnosable, and maintainable

Scope:

- one-command install/setup
- diagnostics and doctor flows
- automated replay, benchmark, live eval, and isolation gating
- release discipline for frozen kernel snapshots

## Risks

### 1. Kernel Drift Debt

A full fork gives control, but creates long-term divergence.

Mitigation:

- keep boundaries strict
- only absorb upstream intentionally
- preserve automated replay and acceptance gates

### 2. Boundary Collapse

If Mente-specific logic leaks into the kernel tree, maintenance cost will spike.

Mitigation:

- keep memory, cron, gateway, eval, and product policy in `mente/`
- only place kernel-essential behavior in `kernel/codex/`

### 3. False Isolation

If the embedded runtime still inherits host config implicitly, the fork will not solve the real problem.

Mitigation:

- make isolation behavior explicit and test it with dedicated acceptance cases

### 4. Packaging Complexity

Bundling kernel + runtime + setup can complicate installation and release.

Mitigation:

- defer polish until Phase D
- first prove clean runtime ownership and correctness

## Acceptance Criteria For The Architecture

The architecture should be considered successful when all of the following are true:

- Mente no longer depends on a public `codex` binary for its primary execution path
- a fresh Mente session cannot be polluted by user-local Codex config or `agents.md`
- memory remains fully owned, observable, and replayable in Mente
- Codex-native tools, plugins, and skills remain available through controlled exposure
- Mente release behavior is stable across machines without hidden local runtime assumptions

## Recommended Next Step

Do not jump directly into the full fork.

The immediate next move should be:

- write a short Phase A implementation plan focused on execution isolation hardening

That plan should define:

- private runtime home strategy
- config/rules suppression behavior
- isolation regression tests
- live acceptance criteria for empty-session purity
