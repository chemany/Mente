# Mente Multi-Agent Lanes Phase 4 Implementation Plan

> **For Mente:** REQUIRED SKILL: Use `executing-plans` to implement this plan task-by-task.

**Goal:** Normalize low-level executor/runtime callbacks into lane-scoped structured progress events and surface those lane events through gateway and TUI without another model summarization pass.

**Architecture:** Add one shared lane-progress normalization layer in `mente/execution_events.py`. Gateway and TUI keep receiving raw runtime events for diagnostics and usage, but they both convert those raw events into `lane.started/progress/blocked/completed/failed` payloads through the same helper, then render director-voice updates from the structured lane events instead of directly formatting raw `kernel.codex.*` events.

**Tech Stack:** Python, pytest via `scripts/run_tests.sh`, Mente execution-event helpers, gateway progress streaming, TUI JSON-RPC event emission

---

### Task 1: Phase-4 failing tests

**Files:**
- Create: `tests/mente/test_execution_events.py`
- Modify: `tests/gateway/test_mente_task_bridge.py`
- Modify: `tests/tui_gateway/test_mente_tui_bridge.py`

**Step 1: Write the failing tests**

Add tests that lock these behaviors:
- low-level command/tool/result signals normalize into `lane.*` structured events with lane, status, headline, detail, timestamp, and task metadata;
- gateway progress output is rendered from lane events in director voice instead of exposing raw runtime event names;
- TUI emits structured `lane.progress` events and mirrors them into visible progress text without requiring another model summary.

**Step 2: Run tests to verify they fail**

Run:
```bash
source .venv/bin/activate && scripts/run_tests.sh tests/mente/test_execution_events.py tests/gateway/test_mente_task_bridge.py tests/tui_gateway/test_mente_tui_bridge.py -q
```

Expected: failures showing there is no shared lane-progress normalization yet.

### Task 2: Shared lane-progress normalization

**Files:**
- Modify: `mente/execution_events.py`
- Test: `tests/mente/test_execution_events.py`

**Step 1: Write minimal implementation**

Add shared helpers that:
- normalize low-level executor/runtime events into `lane.started`, `lane.progress`, and `lane.blocked`;
- synthesize `lane.completed` / `lane.failed` from final `ExecutionResult`;
- attach stable structured fields needed by downstream surfaces.

**Step 2: Run focused tests**

Run:
```bash
source .venv/bin/activate && scripts/run_tests.sh tests/mente/test_execution_events.py -q
```

Expected: normalization tests pass.

### Task 3: Gateway director-voice progress

**Files:**
- Modify: `gateway/run.py`
- Test: `tests/gateway/test_mente_task_bridge.py`

**Step 1: Write minimal implementation**

Teach gateway progress handling to:
- keep raw events for diagnostics only;
- convert them to lane events with the shared normalizer;
- render lane event headlines/details into director-voice progress lines and checkpoint summaries;
- synthesize a terminal lane event from the final turn result for completion/failure summaries.

**Step 2: Run focused tests**

Run:
```bash
source .venv/bin/activate && scripts/run_tests.sh tests/gateway/test_mente_task_bridge.py -q
```

Expected: gateway structured-progress tests pass.

### Task 4: TUI lane-progress emission

**Files:**
- Modify: `tui_gateway/server.py`
- Test: `tests/tui_gateway/test_mente_tui_bridge.py`

**Step 1: Write minimal implementation**

Teach the TUI bridge to:
- normalize raw runtime events into lane events with the shared helper;
- emit `lane.progress`/`lane.completed`/`lane.failed` JSON-RPC events;
- mirror the lane progress into lightweight visible `thinking.delta` text so the current UI shows director-voice progress without a frontend rewrite.

**Step 2: Run focused tests**

Run:
```bash
source .venv/bin/activate && scripts/run_tests.sh tests/tui_gateway/test_mente_tui_bridge.py -q
```

Expected: TUI structured-progress tests pass.

### Task 5: Regression verification

**Files:**
- Test: `tests/mente/test_execution_events.py`
- Test: `tests/gateway/test_mente_task_bridge.py`
- Test: `tests/tui_gateway/test_mente_tui_bridge.py`
- Test: `tests/mente/test_bridge_integration.py`
- Test: `tests/mente/test_codex_executor.py`

**Step 1: Run targeted regression suite**

Run:
```bash
source .venv/bin/activate && scripts/run_tests.sh tests/mente/test_execution_events.py tests/gateway/test_mente_task_bridge.py tests/tui_gateway/test_mente_tui_bridge.py tests/mente/test_bridge_integration.py tests/mente/test_codex_executor.py -q
```

Expected: structured progress does not regress lane routing, prompt specialization, or existing executor integration.
