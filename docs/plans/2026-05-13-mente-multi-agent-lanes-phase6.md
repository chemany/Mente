# Mente Multi-Agent Lanes Phase 6 Implementation Plan

> **For Mente:** REQUIRED SKILL: Use `executing-plans` to implement this plan task-by-task.

**Goal:** Introduce thin lane handoff capsules for status-style follow-up turns so Mente can answer "做到哪了 / 刚才在做什么 / 当前进度" with lighter context while preserving Codex runtime execution for real work.

**Architecture:** Reuse the existing per-lane recent-task snapshot as the source of truth, but add one thinner "handoff capsule" rendering path plus deterministic status-query routing. Gateway and TUI should route pure status follow-ups to the `director` lane, inject only the bounded capsule for the most relevant active lane, and avoid replaying heavier fallback history when a capsule is available.

**Tech Stack:** Python, pytest via `scripts/run_tests.sh`, gateway session persistence, Mente bridge routing, gateway runtime continuity, TUI continuity wrapper

---

### Task 1: Phase-6 failing tests

**Files:**
- Modify: `tests/gateway/test_gateway_runtime_continuity.py`
- Modify: `tests/mente/test_bridge_integration.py`
- Modify: `tests/tui_gateway/test_mente_tui_bridge.py`

**Step 1: Write the failing tests**

Add tests that lock these behaviors:
- status-style follow-up prompts such as `做到哪了` / `当前进度` stay on the `director` lane instead of resuming the active specialist lane;
- gateway task building injects a thin lane handoff capsule for status-style follow-ups instead of the heavier `Recent active task snapshot:` fact;
- when a handoff capsule is available, gateway continuity planning does not require fallback history replay for the director status turn;
- TUI uses the same capsule-oriented follow-up behavior and keeps engineering continuity untouched for later real `继续` execution turns.

**Step 2: Run tests to verify they fail**

Run:
```bash
source .venv/bin/activate && scripts/run_tests.sh tests/gateway/test_gateway_runtime_continuity.py tests/mente/test_bridge_integration.py tests/tui_gateway/test_mente_tui_bridge.py -q
```

Expected: failures showing status follow-ups still inject the heavier recent snapshot path and TUI has no thin capsule context.

### Task 2: Thin handoff capsule rendering

**Files:**
- Modify: `mente/integrations/bridge.py`
- Test: `tests/mente/test_bridge_integration.py`

**Step 1: Write minimal implementation**

Add one bounded lane handoff capsule renderer that:
- derives a short fact from the existing recent-task snapshot fields;
- includes lane, status, latest summary, top follow-up items, and recent artifacts when present;
- is used for status-style follow-up turns instead of the heavier recent-task snapshot fact.

**Step 2: Run focused tests**

Run:
```bash
source .venv/bin/activate && scripts/run_tests.sh tests/mente/test_bridge_integration.py -q
```

Expected: bridge tests pass for thin capsule injection and routing.

### Task 3: Gateway status-follow-up continuity planning

**Files:**
- Modify: `gateway/run.py`
- Test: `tests/gateway/test_gateway_runtime_continuity.py`

**Step 1: Write minimal implementation**

Teach the gateway continuity planner to:
- recognize status-style follow-up prompts deterministically;
- keep those turns on the `director` lane even when another lane is active;
- prefer a thin start with no fallback history replay when a recent lane capsule already exists.

**Step 2: Run focused tests**

Run:
```bash
source .venv/bin/activate && scripts/run_tests.sh tests/gateway/test_gateway_runtime_continuity.py -q
```

Expected: gateway continuity tests pass for director status follow-ups.

### Task 4: TUI lane capsule parity

**Files:**
- Modify: `tui_gateway/server.py`
- Modify: `mente/integrations/bridge.py`
- Test: `tests/tui_gateway/test_mente_tui_bridge.py`

**Step 1: Write minimal implementation**

Teach `MenteTuiAgent` to:
- persist one recent-task snapshot per lane from completed results;
- pass the active lane snapshot into `build_tui_task` / `run_tui_task` for status follow-ups;
- keep later `继续` prompts resuming the engineering continuity as before.

**Step 2: Run focused tests**

Run:
```bash
source .venv/bin/activate && scripts/run_tests.sh tests/tui_gateway/test_mente_tui_bridge.py -q
```

Expected: TUI status follow-ups use thin capsules while execution continuity remains lane-safe.

### Task 5: Regression verification

**Files:**
- Test: `tests/gateway/test_session.py`
- Test: `tests/gateway/test_gateway_runtime_continuity.py`
- Test: `tests/gateway/test_mente_task_bridge.py`
- Test: `tests/mente/test_bridge_integration.py`
- Test: `tests/tui_gateway/test_mente_tui_bridge.py`

**Step 1: Run targeted regression suite**

Run:
```bash
source .venv/bin/activate && scripts/run_tests.sh tests/gateway/test_session.py tests/gateway/test_gateway_runtime_continuity.py tests/gateway/test_mente_task_bridge.py tests/mente/test_bridge_integration.py tests/tui_gateway/test_mente_tui_bridge.py -q
```

Expected: status follow-up capsules land without regressing lane continuity, progress delivery, or existing continuation behavior.
