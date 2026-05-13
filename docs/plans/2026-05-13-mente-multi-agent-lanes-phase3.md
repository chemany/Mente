# Mente Multi-Agent Lanes Phase 3 Implementation Plan

> **For Mente:** REQUIRED SKILL: Use `executing-plans` to implement this plan task-by-task.

**Goal:** Bind Mente prompt selection to the deterministic lane model so `director` uses a thin conversation prompt while `research`, `writing`, and `config_admin` use specialist prompt profiles.

**Architecture:** Reuse phase-2 lane metadata already attached to tasks. Make both prompt rendering and runtime base-instruction selection read the lane/task-profile from `ExecutionRequest.metadata`, with task-profile-specific flows (`content_publishing`, `deep_research`, `config_admin`) taking precedence over generic lane defaults.

**Tech Stack:** Python, pytest via `scripts/run_tests.sh`, Mente executor prompt rendering, private Codex runtime config adaptation

---

### Task 1: Phase-3 prompt/profile tests

**Files:**
- Modify: `tests/mente/test_codex_executor.py`
- Modify: `tests/mente/test_runtime_config.py`

**Step 1: Write the failing tests**

Add tests that lock these behaviors:
- `metadata["lane"] == "director"` uses the thin prompt profile;
- `metadata["lane"] == "research"` keeps a full prompt but uses research-specific execution guidance instead of engineering guidance;
- `metadata["lane"] == "writing"` keeps a full prompt but uses writing-specific execution guidance;
- runtime config switches to `director`, `research`, and `writing` specialist base instructions from lane metadata;
- profile overrides for lane profiles are applied from `codex.profiles.<lane>`.

**Step 2: Run tests to verify they fail**

Run:
```bash
source .venv/bin/activate && scripts/run_tests.sh tests/mente/test_codex_executor.py tests/mente/test_runtime_config.py -q
```

Expected: failures showing lane-aware prompt specialization is not fully implemented yet.

### Task 2: Lane-aware prompt rendering

**Files:**
- Modify: `mente/executors/prompting.py`
- Test: `tests/mente/test_codex_executor.py`

**Step 1: Write minimal implementation**

Add shared request-lane helpers and specialize prompt rendering so:
- `director` uses the existing thin prompt;
- `research` gets research-oriented execution guidance;
- `writing` gets writing-oriented execution guidance;
- existing workflow-policy blocks for deep research / publishing / config-admin still remain intact.

**Step 2: Run focused tests**

Run:
```bash
source .venv/bin/activate && scripts/run_tests.sh tests/mente/test_codex_executor.py -q
```

Expected: prompt rendering tests pass.

### Task 3: Lane-aware runtime base instructions

**Files:**
- Modify: `mente/executors/runtime_config.py`
- Test: `tests/mente/test_runtime_config.py`

**Step 1: Write minimal implementation**

Add specialist base-instruction constants and lane-aware profile resolution so:
- `director` uses thin conversation base instructions;
- `research` uses research base instructions;
- `writing` uses writing base instructions;
- `content_publishing` and `config_admin` task profiles still override generic lane defaults;
- lane profile overrides from `codex.profiles` can apply without affecting unrelated lanes.

**Step 2: Run focused tests**

Run:
```bash
source .venv/bin/activate && scripts/run_tests.sh tests/mente/test_runtime_config.py -q
```

Expected: runtime-config specialization tests pass.

### Task 4: Regression verification

**Files:**
- Test: `tests/mente/test_codex_executor.py`
- Test: `tests/mente/test_runtime_config.py`
- Test: `tests/mente/test_bridge_integration.py`

**Step 1: Run targeted regression suite**

Run:
```bash
source .venv/bin/activate && scripts/run_tests.sh tests/mente/test_codex_executor.py tests/mente/test_runtime_config.py tests/mente/test_bridge_integration.py -q
```

Expected: prompt specialization does not regress phase-2 lane routing or existing execution prompt behavior.
