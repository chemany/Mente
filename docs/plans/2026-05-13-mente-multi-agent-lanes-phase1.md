# Mente Multi-Agent Lanes Phase 1 Implementation Plan

> **For Mente:** REQUIRED SKILL: Use `executing-plans` to implement this plan task-by-task.

**Goal:** Convert runtime continuity from a single session-level binding into a per-lane registry with backward compatibility and a default `director` lane.

**Architecture:** Keep routing behavior unchanged in phase 1 and only widen the continuity storage/read-write path. `SessionStore` becomes the source of truth for lane-scoped continuity payloads, while gateway and TUI helpers keep defaulting to `director` unless a lane is provided explicitly.

**Tech Stack:** Python, pytest via `scripts/run_tests.sh`, gateway session persistence JSON, Mente gateway/TUI continuity helpers

---

### Task 1: Phase-1 compatibility tests

**Files:**
- Modify: `tests/gateway/test_session.py`
- Modify: `tests/gateway/test_gateway_runtime_continuity.py`
- Modify: `tests/tui_gateway/test_mente_tui_bridge.py`

**Step 1: Write the failing tests**

Add tests that lock these behaviors:
- `SessionStore` supports independent continuity payloads for `director` and `engineering`.
- Omitting `lane` still reads/writes the `director` lane.
- Legacy `runtime_continuity.json` entries load as `director` lane payloads.
- Gateway continuity helpers pass an explicit lane through bind/invalidate paths.
- `MenteTuiAgent` stores continuity by lane and defaults to `director`.

**Step 2: Run tests to verify they fail**

Run:
```bash
source .venv/bin/activate && scripts/run_tests.sh tests/gateway/test_session.py tests/gateway/test_gateway_runtime_continuity.py tests/tui_gateway/test_mente_tui_bridge.py -q
```

Expected: failures showing lane-aware continuity APIs/state are not implemented yet.

### Task 2: Session store per-lane continuity registry

**Files:**
- Modify: `gateway/session.py`
- Test: `tests/gateway/test_session.py`

**Step 1: Write minimal implementation**

Update `SessionStore` to:
- store runtime continuity internally as `session_id -> lane -> payload`;
- expose `get_runtime_continuity(session_id, lane="director")`;
- expose `bind_runtime_continuity(..., lane="director")`;
- expose `invalidate_runtime_continuity(..., lane="director")`;
- expose `clear_runtime_continuity(session_id, lane="director")`;
- load legacy disk payloads by wrapping them into the `director` lane;
- save all payloads in the new registry format.

**Step 2: Run focused tests**

Run:
```bash
source .venv/bin/activate && scripts/run_tests.sh tests/gateway/test_session.py -q
```

Expected: session continuity tests pass.

### Task 3: Gateway continuity lane plumbing

**Files:**
- Modify: `gateway/run.py`
- Test: `tests/gateway/test_gateway_runtime_continuity.py`

**Step 1: Write minimal implementation**

Thread a `lane` argument through continuity helpers, defaulting to `director` in phase 1. Ensure bind/invalidate calls preserve existing behavior while targeting the selected lane.

**Step 2: Run focused tests**

Run:
```bash
source .venv/bin/activate && scripts/run_tests.sh tests/gateway/test_gateway_runtime_continuity.py -q
```

Expected: gateway continuity helper tests pass.

### Task 4: TUI continuity lane state

**Files:**
- Modify: `tui_gateway/server.py`
- Test: `tests/tui_gateway/test_mente_tui_bridge.py`

**Step 1: Write minimal implementation**

Replace the single `_continuity_payload` slot with a lane-indexed registry, but keep phase-1 behavior pinned to `director`. Use the selected lane for resume/start decisions and update the lane payload after each turn.

**Step 2: Run focused tests**

Run:
```bash
source .venv/bin/activate && scripts/run_tests.sh tests/tui_gateway/test_mente_tui_bridge.py -q
```

Expected: TUI continuity tests pass.

### Task 5: Regression verification

**Files:**
- Test: `tests/gateway/test_session.py`
- Test: `tests/gateway/test_gateway_runtime_continuity.py`
- Test: `tests/tui_gateway/test_mente_tui_bridge.py`
- Test: `tests/gateway/test_mente_task_bridge.py`
- Test: `tests/mente/test_bridge_integration.py`

**Step 1: Run the targeted regression suite**

Run:
```bash
source .venv/bin/activate && scripts/run_tests.sh tests/gateway/test_session.py tests/gateway/test_gateway_runtime_continuity.py tests/tui_gateway/test_mente_tui_bridge.py tests/gateway/test_mente_task_bridge.py tests/mente/test_bridge_integration.py -q
```

Expected: all targeted phase-1 continuity tests pass without regressions.
