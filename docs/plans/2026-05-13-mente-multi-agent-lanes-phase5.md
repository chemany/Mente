# Mente Multi-Agent Lanes Phase 5 Implementation Plan

> **For Mente:** REQUIRED SKILL: Use `executing-plans` to implement this plan task-by-task.

**Goal:** Prefer active lane reuse for continuation turns and make recent-task snapshots lane-aware so follow-up requests resume the correct specialist lane instead of collapsing back to director.

**Architecture:** Extend the gateway session store so recent-task snapshots are persisted per `session + lane`, with legacy single-payload snapshots loading into the `director` lane. Add one deterministic continuation-lane hint path in the bridge/router layer so `continue/resume/继续刚才` requests reuse the most relevant active lane in gateway and TUI, while unrelated new requests still route by existing heuristics.

**Tech Stack:** Python, pytest via `scripts/run_tests.sh`, gateway session persistence, Mente bridge routing, gateway runtime continuity, TUI continuity wrapper

---

### Task 1: Phase-5 failing tests

**Files:**
- Modify: `tests/gateway/test_session.py`
- Modify: `tests/gateway/test_gateway_runtime_continuity.py`
- Modify: `tests/mente/test_bridge_integration.py`
- Modify: `tests/tui_gateway/test_mente_tui_bridge.py`

**Step 1: Write the failing tests**

Add tests that lock these behaviors:
- recent-task snapshots persist independently per lane and still load legacy disk payloads into the `director` lane;
- `continue/resume/继续刚才的任务` prefers the active lane hint instead of defaulting back to `director`;
- gateway task building uses the lane-aware recent snapshot to route follow-up continuation turns to the correct specialist lane;
- TUI continuation reuses the previous engineering lane even when the second prompt no longer contains engineering keywords.

**Step 2: Run tests to verify they fail**

Run:
```bash
source .venv/bin/activate && scripts/run_tests.sh tests/gateway/test_session.py tests/gateway/test_gateway_runtime_continuity.py tests/mente/test_bridge_integration.py tests/tui_gateway/test_mente_tui_bridge.py -q
```

Expected: failures showing snapshots are still session-global and continuation turns still fall back to `director`.

### Task 2: Lane-aware snapshot persistence

**Files:**
- Modify: `gateway/session.py`
- Test: `tests/gateway/test_session.py`

**Step 1: Write minimal implementation**

Teach `SessionStore` to:
- normalize `recent_task_snapshots.json` into a `session -> lane -> payload` registry;
- support `get_recent_task_snapshot(..., lane=...)`, `bind_recent_task_snapshot(..., lane=...)`, and `clear_recent_task_snapshot(..., lane=...)`;
- provide one helper for looking up the most recent active snapshot across lanes for continuation routing.

**Step 2: Run focused tests**

Run:
```bash
source .venv/bin/activate && scripts/run_tests.sh tests/gateway/test_session.py -q
```

Expected: snapshot lane-isolation tests pass.

### Task 3: Continuation lane hints in routing

**Files:**
- Modify: `mente/integrations/bridge.py`
- Modify: `gateway/run.py`
- Test: `tests/gateway/test_gateway_runtime_continuity.py`
- Test: `tests/mente/test_bridge_integration.py`

**Step 1: Write minimal implementation**

Add a deterministic continuation hint path that:
- reuses a valid active lane for `continue/resume/继续刚才` requests before the default director fallback;
- uses the lane-aware recent snapshot metadata as a follow-up routing hint;
- keeps artifact-delivery routing and unrelated new-turn routing unchanged.

**Step 2: Run focused tests**

Run:
```bash
source .venv/bin/activate && scripts/run_tests.sh tests/gateway/test_gateway_runtime_continuity.py tests/mente/test_bridge_integration.py -q
```

Expected: gateway routing and bridge continuation tests pass.

### Task 4: TUI continuation lane reuse

**Files:**
- Modify: `tui_gateway/server.py`
- Test: `tests/tui_gateway/test_mente_tui_bridge.py`

**Step 1: Write minimal implementation**

Teach `MenteTuiAgent` to:
- prefer the most recently active continuity lane for generic continuation prompts;
- preserve existing lane separation so director and engineering continuities stay independent.

**Step 2: Run focused tests**

Run:
```bash
source .venv/bin/activate && scripts/run_tests.sh tests/tui_gateway/test_mente_tui_bridge.py -q
```

Expected: generic continuation prompts resume the correct TUI lane.

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

Expected: lane reuse works without regressing continuity persistence, follow-up routing, or existing gateway/TUI behavior.
