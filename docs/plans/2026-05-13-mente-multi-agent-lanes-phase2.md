# Mente Multi-Agent Lanes Phase 2 Implementation Plan

> **For Mente:** REQUIRED SKILL: Use `executing-plans` to implement this plan task-by-task.

**Goal:** Add a deterministic conversation router that selects the Mente lane before task construction and continuity lookup, and persist lane metadata into task/workflow contracts.

**Architecture:** Centralize lane selection in `mente/integrations/bridge.py` so gateway and TUI share one deterministic-first router. The router returns a lane decision from existing workflow hints (`task_profile`, artifact follow-up) plus obvious engineering/chat heuristics; gateway and TUI then use that lane for continuity lookup and task metadata.

**Tech Stack:** Python, pytest via `scripts/run_tests.sh`, Mente bridge task builders, gateway/TUI continuity helpers

---

### Task 1: Phase-2 routing tests

**Files:**
- Modify: `tests/mente/test_bridge_integration.py`
- Modify: `tests/tui_gateway/test_mente_tui_bridge.py`
- Modify: `tests/gateway/test_gateway_runtime_continuity.py`

**Step 1: Write the failing tests**

Add tests that lock these behaviors:
- simple chat/identity turns route to `director`;
- obvious coding/debugging turns route to `engineering`;
- deep-research turns route to `research`;
- content-publishing turns route to `writing`;
- config-admin turns route to `config_admin`;
- gateway/TUI continuity uses the selected lane instead of always `director`;
- `workflow_contract` includes lane metadata and lane-scoped continuity metadata.

**Step 2: Run tests to verify they fail**

Run:
```bash
source .venv/bin/activate && scripts/run_tests.sh tests/mente/test_bridge_integration.py tests/tui_gateway/test_mente_tui_bridge.py tests/gateway/test_gateway_runtime_continuity.py -q
```

Expected: failures showing lane routing metadata and lane-aware continuity selection are not implemented yet.

### Task 2: Deterministic router and contract metadata

**Files:**
- Modify: `mente/integrations/bridge.py`
- Modify: `mente/feature_flags.py`
- Test: `tests/mente/test_bridge_integration.py`

**Step 1: Write minimal implementation**

Add shared lane constants and a small route-result model. Implement one deterministic router that:
- uses existing recognized workflow hints first;
- maps recognized workflows onto lanes;
- treats obvious coding/debugging requests as `engineering`;
- falls back to `director`.

Persist the route result into:
- `metadata["lane"]`;
- `workflow_contract["lane"]`;
- `workflow_contract["continuity"]` lane-scoped metadata.

**Step 2: Run focused tests**

Run:
```bash
source .venv/bin/activate && scripts/run_tests.sh tests/mente/test_bridge_integration.py -q
```

Expected: bridge routing and workflow-contract tests pass.

### Task 3: Gateway lane selection before continuity lookup

**Files:**
- Modify: `gateway/run.py`
- Test: `tests/gateway/test_gateway_runtime_continuity.py`

**Step 1: Write minimal implementation**

Resolve the lane before gateway continuity planning so:
- `get_runtime_continuity()` reads the selected lane;
- continuity invalidation/bind keeps using that same lane;
- gateway task construction receives matching lane metadata.

**Step 2: Run focused tests**

Run:
```bash
source .venv/bin/activate && scripts/run_tests.sh tests/gateway/test_gateway_runtime_continuity.py -q
```

Expected: gateway lane-selection and continuity tests pass.

### Task 4: TUI lane selection and lane-specific continuity state

**Files:**
- Modify: `tui_gateway/server.py`
- Modify: `mente/integrations/bridge.py`
- Test: `tests/tui_gateway/test_mente_tui_bridge.py`

**Step 1: Write minimal implementation**

Replace the phase-1 placeholder lane resolver with the shared deterministic router so TUI:
- selects `engineering` for obvious coding turns and `director` for casual turns;
- resumes continuity only within the selected lane;
- writes matching `metadata["lane"]` into built tasks.

**Step 2: Run focused tests**

Run:
```bash
source .venv/bin/activate && scripts/run_tests.sh tests/tui_gateway/test_mente_tui_bridge.py -q
```

Expected: TUI lane-routing and continuity tests pass.

### Task 5: Regression verification

**Files:**
- Test: `tests/mente/test_bridge_integration.py`
- Test: `tests/tui_gateway/test_mente_tui_bridge.py`
- Test: `tests/gateway/test_gateway_runtime_continuity.py`
- Test: `tests/gateway/test_mente_task_bridge.py`

**Step 1: Run targeted regression suite**

Run:
```bash
source .venv/bin/activate && scripts/run_tests.sh tests/mente/test_bridge_integration.py tests/tui_gateway/test_mente_tui_bridge.py tests/gateway/test_gateway_runtime_continuity.py tests/gateway/test_mente_task_bridge.py -q
```

Expected: deterministic router changes do not regress existing gateway/TUI bridge behavior.
