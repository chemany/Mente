# Runtime Shell Reduction Implementation Plan

> **For Mente:** Use `executing-plans` to implement this plan task-by-task.

**Goal:** Reduce Codex runtime per-turn token overhead in Mente by shrinking `base_instructions`, removing redundant turn-level overrides, and moving stable execution constraints to thread/session scope where the upstream protocol already supports it.

**Architecture:** Keep Mente's thin prompt and on-demand memory design unchanged. Optimize the vendored Codex runtime in three layers: model/session bootstrap, thread-vs-turn configuration handoff, and model-visible context assembly. Prefer bridge/config solutions first; only patch vendored `codex-rs` where the current `codex exec` path hardcodes redundant per-turn fields.

**Tech Stack:** Mente Python bridge, vendored `codex-rs` exec/core/app-server, rollout JSONL diagnostics, Python regression tests, targeted Rust crate tests.

---

### Task 1: Baseline And Ownership Map

**Files:**
- Inspect: `mente/executors/codex.py`
- Inspect: `kernel/codex/runtime/launcher.py`
- Inspect: `kernel/codex/upstream/codex-rs/exec/src/lib.rs`
- Inspect: `kernel/codex/upstream/codex-rs/core/src/session/mod.rs`
- Inspect: `kernel/codex/upstream/codex-rs/models-manager/src/model_info.rs`
- Inspect: `kernel/codex/upstream/codex-rs/core/templates/model_instructions/gpt-5.2-codex_instructions_template.md`
- Inspect: `/home/jason/.mente/codex/sessions/**/rollout-*.jsonl`
- Test: `tests/mente/test_codex_executor.py`

**Step 1: Capture the current shell composition**

Document the real ownership split:
- Mente contributes the user task prompt via `render_execution_prompt()`.
- The vendored runtime contributes `base_instructions`.
- The runtime session layer contributes model-visible developer/context sections through `build_initial_context()`.
- `codex exec` contributes thread and turn RPC defaults in `exec/src/lib.rs`.

**Step 2: Record the current high-cost sections**

Use the rollout `session_meta`, `turn_context`, and token-count events to capture:
- `base_instructions` length
- first-turn `input_tokens`
- resumed-turn `input_tokens`
- `cached_input_tokens`
- `time_to_first_token_ms`

Expected outcome: a short before-state table that separates:
- Mente prompt cost
- model bootstrap cost
- thread/turn control-plane cost

**Step 3: Freeze the decision boundary**

Write down these constraints before any code change:
- Mente still owns memory, skills, and tool policy.
- Internal executor remains Codex.
- Any reduction must preserve prompt caching and continuity.
- Any change that only shrinks rollout logging but not model-visible input is second priority.

**Step 4: Verify the current behavior is reproducible**

Run:
```bash
scripts/run_tests.sh tests/mente/test_codex_executor.py
```

Expected: current executor contract still passes before optimization work begins.

**Step 5: Commit**

```bash
git add docs/plans/2026-05-08-runtime-shell-reduction-plan.md
git commit -m "docs: add runtime shell reduction plan"
```

### Task 2: Compress `base_instructions` At The Lowest-Risk Layer

**Files:**
- Modify: `mente/executors/runtime_config.py`
- Modify: `kernel/codex/config.py`
- Inspect/possibly modify: `kernel/codex/upstream/codex-rs/models-manager/src/model_info.rs`
- Inspect/possibly modify: `kernel/codex/upstream/codex-rs/core/templates/model_instructions/gpt-5.2-codex_instructions_template.md`
- Test: `tests/mente/test_codex_executor.py`
- Test: `tests/mente/test_bridge_integration.py`

**Step 1: Prefer config override over upstream prompt fork**

Implement the first attempt with a Mente-owned runtime config override:
- inject a smaller `codex.base_instructions` string or file-backed equivalent through Mente runtime config
- do not fork the vendored upstream template unless the config path proves insufficient

Rationale: this keeps the optimization in the Mente-owned seam and reduces upstream merge pain.

**Step 2: Define what must remain in the slim base prompt**

Keep only invariants that the runtime truly needs every turn:
- coding-agent role
- workspace/tool execution expectations
- file editing safety constraints
- answer formatting expectations required by the bridge

Remove or relocate:
- duplicated meta-explanation
- verbose persona prose
- repeated platform instructions already enforced outside the runtime

**Step 3: Add a size regression test**

Add a targeted test asserting the effective Mente runtime `base_instructions` stays under a chosen size budget.

Example shape:
```python
def test_runtime_base_instructions_budget():
    instructions = resolve_effective_runtime_base_instructions(...)
    assert len(instructions) < EXPECTED_BUDGET
```

**Step 4: Re-run focused verification**

Run:
```bash
scripts/run_tests.sh tests/mente/test_codex_executor.py tests/mente/test_bridge_integration.py
```

Expected: no contract breakage in bridge or executor tests.

**Step 5: Commit**

```bash
git add mente/executors/runtime_config.py kernel/codex/config.py tests/mente/test_codex_executor.py tests/mente/test_bridge_integration.py
git commit -m "feat: slim mente runtime base instructions"
```

### Task 3: Stop Repeating Stable Thread Settings On Every Turn

**Files:**
- Modify: `kernel/codex/upstream/codex-rs/exec/src/lib.rs`
- Inspect: `kernel/codex/upstream/sdk/python/src/codex_app_server/generated/v2_all.py`
- Test: `tests/mente/test_codex_bridge.py`
- Test: `tests/mente/test_codex_executor.py`
- Test: `kernel/codex/upstream/codex-rs/exec/src/main_tests.rs`

**Step 1: Confirm which fields are already session-scoped by protocol**

Thread-level APIs already support stable configuration:
- `ThreadStartParams.baseInstructions`
- `ThreadStartParams.developerInstructions`
- `ThreadStartParams.approvalPolicy`
- `ThreadStartParams.permissionProfile`
- `ThreadStartParams.cwd`

Turn-level APIs currently restate some of these:
- `TurnStartParams.approvalPolicy`
- `TurnStartParams.cwd`
- `TurnStartParams.effort`

**Step 2: Patch `codex exec` to omit unchanged turn defaults**

Change the exec path so resumed or continuing turns do not send thread-stable values again unless they actually changed.

Preferred rule:
- send thread-stable defaults at `thread/start` and `thread/resume`
- omit the same fields from `turn/start` when the turn has no override

**Step 3: Keep continuity semantics intact**

Do not break:
- `resume <thread_id>`
- first-turn setup
- thread-local override persistence for future turns

**Step 4: Add regression tests**

Add tests for:
- new thread start still gets the correct defaults
- resumed thread turn start omits unchanged `cwd` / `approval_policy` / `effort`
- an explicit override still appears when changed

**Step 5: Run targeted verification**

Run:
```bash
scripts/run_tests.sh tests/mente/test_codex_bridge.py tests/mente/test_codex_executor.py
cd kernel/codex/upstream/codex-rs && cargo test -p codex-exec
```

Expected: Python bridge tests and vendored exec tests both pass.

**Step 6: Commit**

```bash
git add kernel/codex/upstream/codex-rs/exec/src/lib.rs tests/mente/test_codex_bridge.py tests/mente/test_codex_executor.py
git commit -m "feat: avoid redundant codex exec turn overrides"
```

### Task 4: Shrink Model-Visible Turn Context, Not Just Logged `turn_context`

**Files:**
- Modify: `kernel/codex/upstream/codex-rs/core/src/session/mod.rs`
- Inspect: `kernel/codex/upstream/codex-rs/core/src/context_manager/updates/*`
- Inspect: `kernel/codex/upstream/codex-rs/core/src/context/collaboration_mode_instructions.rs`
- Test: `kernel/codex/upstream/codex-rs/core/src/session/tests.rs`

**Step 1: Separate logged state from prompt-visible state**

Do not optimize the persisted `TurnContextItem` first. Optimize the sections that actually become developer/context messages:
- permissions instructions
- memory tool instructions
- skills inventory
- plugins inventory
- apps inventory
- environment context

**Step 2: Rank each section by savings versus risk**

Recommended order:
1. permissions instructions deduplication
2. skills/plugins/apps inventory trimming
3. environment-context compaction
4. developer-instruction consolidation

**Step 3: Prefer conditional omission over semantic rewrite**

For each section:
- omit it entirely when the runtime can already infer the capability elsewhere
- replace long inventories with compact summaries plus on-demand discovery
- avoid changing the meaning of safety-critical instructions

**Step 4: Add tests around steady-state diffs**

Cover:
- first turn still injects required full context
- resumed turns only emit compact diffs
- no accidental reinjection of full permissions/skills context when nothing changed

**Step 5: Run targeted verification**

Run:
```bash
cd kernel/codex/upstream/codex-rs && cargo test -p codex-core session::
```

Expected: no regression in session diffing and resume behavior.

**Step 6: Commit**

```bash
git add kernel/codex/upstream/codex-rs/core/src/session/mod.rs
git commit -m "feat: compact codex runtime turn context"
```

### Task 5: Prove Session-Level Reduction With End-To-End Metrics

**Files:**
- Inspect: `/home/jason/.mente/logs/agent.log`
- Inspect: `/home/jason/.mente/logs/gateway.log`
- Inspect: `/home/jason/.mente/codex/sessions/**/rollout-*.jsonl`
- Test: `tests/mente/test_hermes_integration.py`
- Test: `tests/mente/test_bridge_integration.py`

**Step 1: Run the same user prompt across TUI and gateway**

Use the same low-entropy prompt for:
- first turn
- second turn
- third turn

Capture:
- `input_tokens`
- `cached_input_tokens`
- `prompt_fingerprint`
- `continuity_status`
- `time_to_first_token_ms`

**Step 2: Verify the expected shape**

Expected after optimization:
- first turn still relatively heavy
- second and later turns carry lower `input_tokens`
- resumed turns preserve high `cached_input_tokens`
- TUI and gateway stay aligned

**Step 3: Add one bridge-level regression test**

Add a high-level test that fails if sessionful resumed turns begin re-injecting a large shell unexpectedly.

**Step 4: Run final focused verification**

Run:
```bash
scripts/run_tests.sh tests/mente/test_hermes_integration.py tests/mente/test_bridge_integration.py tests/mente/test_codex_executor.py tests/mente/test_codex_bridge.py
```

Expected: all targeted Mente regression tests pass.

**Step 5: Commit**

```bash
git add tests/mente/test_hermes_integration.py tests/mente/test_bridge_integration.py tests/mente/test_codex_executor.py tests/mente/test_codex_bridge.py
git commit -m "test: lock runtime shell token regressions"
```

### Task 6: Fallback Path If `codex exec` Cannot Be Trimmed Cleanly

**Files:**
- Modify: `kernel/codex/runtime/runner.py`
- Modify: `kernel/codex/bridge/entrypoints.py`
- Modify: `mente/executors/codex.py`
- Inspect: `kernel/codex/upstream/sdk/python/src/codex_app_server/api.py`
- Test: `tests/mente/test_kernel_runner.py`

**Step 1: Decide whether to bypass `codex exec` for sessionful runs**

If `codex exec` continues to force large turn-level control payloads, prototype a Mente-owned direct app-server path for sessionful execution only.

**Step 2: Keep the stateless path unchanged**

Do not replace the existing stateless execution path unless the direct app-server path proves strictly better and equally reliable.

**Step 3: Gate the fallback path**

Add a feature flag so Mente can compare:
- legacy exec-based sessionful mode
- direct app-server sessionful mode

**Step 4: Verify equivalence**

Run:
```bash
scripts/run_tests.sh tests/mente/test_kernel_runner.py tests/mente/test_codex_executor.py
```

Expected: both paths produce the same Mente bridge contract.

**Step 5: Commit**

```bash
git add kernel/codex/runtime/runner.py kernel/codex/bridge/entrypoints.py mente/executors/codex.py tests/mente/test_kernel_runner.py
git commit -m "feat: add direct app-server sessionful runtime path"
```

## Decision Notes

- **First priority:** shrink `base_instructions` without forking more upstream than necessary.
- **Second priority:** stop `codex exec` from restating stable thread defaults on every turn.
- **Third priority:** compact model-visible developer/context sections assembled in `build_initial_context()`.
- **Do not over-prioritize** shrinking persisted `turn_context` JSON if it does not materially reduce prompt tokens or latency.
- **Do not let runtime own Mente memory/skill policy** just to save tokens.

## Success Criteria

- Steady-state resumed turns show materially lower `input_tokens` than the current ~16k-17k range.
- `cached_input_tokens` remain high on resumed TUI and gateway turns.
- No regression in continuity, tool execution, or output schema enforcement.
- No regression in Mente-owned memory/tool-policy boundaries.
