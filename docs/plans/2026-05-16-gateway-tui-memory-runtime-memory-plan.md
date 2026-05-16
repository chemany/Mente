# Gateway/TUI Runtime Memory Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Enable `gateway`/`tui` Codex runtime turns and delegated child workers to read and write canonical Mente memory through `state.db`, with prompt preload backed by summary caches.

**Architecture:** Keep `state.db` / `mente_memories` as the canonical store. Expose runtime memory MCP bridge tools for generic `gateway` and `tui` conversation tasks, preload worker-facing summary caches before generic memories, and persist a per-lane worker summary cache after worker turns so child runs start from compact handoff state before querying the full session memory store.

**Tech Stack:** Python, Pydantic models, SQLite repositories, vendored Codex runtime bridge MCP, pytest via `scripts/run_tests.sh`.

---

### Task 1: Open runtime memory bridge for gateway and TUI conversations

**Files:**
- Modify: `mente/executors/tool_policy.py`
- Test: `tests/mente/test_tool_policy.py`
- Test: `tests/tui_gateway/test_mente_tui_bridge.py`
- Test: `tests/mente/test_bridge_integration.py`

**Step 1: Write the failing tests**

Assert that generic `gateway` and `tui` conversation policies expose `mente_memory_query` and `mente_memory_save`, and that second-turn gateway requests inherit the bridge tools instead of an empty list.

**Step 2: Run test to verify it fails**

Run: `scripts/run_tests.sh tests/mente/test_tool_policy.py tests/tui_gateway/test_mente_tui_bridge.py tests/mente/test_bridge_integration.py -q`

Expected: policy / bridge inheritance assertions fail because `gateway` and `tui` still expose no runtime memory bridge tools.

**Step 3: Write minimal implementation**

Enable generic `gateway` and `tui` conversation profiles to expose runtime memory bridge tools while preserving narrower profile-specific overrides such as content publishing.

**Step 4: Run test to verify it passes**

Run the same test command and confirm the policy and inheritance assertions pass.

**Step 5: Commit**

```bash
git add mente/executors/tool_policy.py tests/mente/test_tool_policy.py tests/tui_gateway/test_mente_tui_bridge.py tests/mente/test_bridge_integration.py
git commit -m "feat: expose runtime memory bridge for gateway and tui"
```

### Task 2: Preload worker summary cache ahead of generic memory injection

**Files:**
- Modify: `mente/memory/context.py`
- Modify: `mente/memory/policy.py`
- Test: `tests/mente/test_context_builder.py`
- Test: `tests/mente/test_codex_executor.py`

**Step 1: Write the failing tests**

Cover a delegated worker request with `worker_lane` and `parent_task_id`, asserting preload order is:
1. lane summary cache
2. session summary cache
3. direct task memory facts

Also assert the runtime prompt advertises `mente_memory_query` for on-demand session reads instead of stuffing ordinary session memories into the prompt.

**Step 2: Run test to verify it fails**

Run: `scripts/run_tests.sh tests/mente/test_context_builder.py tests/mente/test_codex_executor.py -q`

Expected: worker summary preload assertions fail because no worker-lane summary cache is retrieved today.

**Step 3: Write minimal implementation**

Extend memory policy/context resolution to retrieve a deterministic per-lane worker summary cache before session summaries when `task.role == worker` and `worker_lane` is set.

**Step 4: Run test to verify it passes**

Run the same tests and confirm preload order and on-demand prompt expectations pass.

**Step 5: Commit**

```bash
git add mente/memory/context.py mente/memory/policy.py tests/mente/test_context_builder.py tests/mente/test_codex_executor.py
git commit -m "feat: preload worker summary cache for delegated runs"
```

### Task 3: Persist worker summary cache after delegated worker turns

**Files:**
- Modify: `mente/integrations/bridge.py`
- Add or Modify: `mente/review/worker_summary_cache.py`
- Test: `tests/mente/test_bridge_integration.py`
- Test: `tests/mente/test_memory_context.py`

**Step 1: Write the failing tests**

Assert that a successful delegated worker turn writes one session-scoped `worker_lane_summary:<lane>` memory row keyed to the current session and that the next worker request preloads that cache.

**Step 2: Run test to verify it fails**

Run: `scripts/run_tests.sh tests/mente/test_bridge_integration.py tests/mente/test_memory_context.py -q`

Expected: cache persistence assertions fail because no worker summary post-turn hook exists.

**Step 3: Write minimal implementation**

Add a deterministic post-turn cache writer for delegated worker conversation tasks and wire it into `_apply_post_turn_conversation_workflow_contract()`.

**Step 4: Run test to verify it passes**

Run the same tests and confirm the persisted cache and next-turn preload behavior pass.

**Step 5: Commit**

```bash
git add mente/integrations/bridge.py mente/review/worker_summary_cache.py tests/mente/test_bridge_integration.py tests/mente/test_memory_context.py
git commit -m "feat: persist worker summary cache for delegated runs"
```

### Task 4: Verify the integrated runtime memory flow

**Files:**
- Test only: existing files from Tasks 1-3

**Step 1: Run focused verification**

Run:

```bash
scripts/run_tests.sh \
  tests/mente/test_tool_policy.py \
  tests/mente/test_bridge_mcp.py \
  tests/mente/test_context_builder.py \
  tests/mente/test_codex_executor.py \
  tests/mente/test_bridge_integration.py \
  tests/tui_gateway/test_mente_tui_bridge.py \
  tests/mente/test_memory_context.py -q
```

**Step 2: Inspect for regressions**

Confirm the runtime memory bridge, prompt preload, and worker summary cache tests all pass under the hermetic wrapper.

**Step 3: Commit final integration if needed**

```bash
git add docs/plans/2026-05-16-gateway-tui-memory-runtime-memory-plan.md
git commit -m "docs: add gateway tui runtime memory plan"
```
