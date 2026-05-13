# Agents Dashboard Page Implementation Plan

> **For Mente:** REQUIRED SKILL: Use `executing-plans` to implement this plan task-by-task.

**Goal:** Add a first-class `Agents` dashboard page and upgrade `/agents` into a fuller operator panel backed by one shared Mente agent inventory data source.

**Architecture:** Extend the Mente agent runtime admin layer into an inventory helper that joins registry metadata, soul text, runtime session files, and runtime DB state. Expose that through new dashboard API endpoints, reuse it in `/agents`, and render a dedicated React page under the existing Hermes dashboard shell.

**Tech Stack:** Python, FastAPI, React, TypeScript, existing dashboard routing/i18n, pytest via `scripts/run_tests.sh`, frontend type-check/build.

---

### Task 1: Lock behavior with failing tests

**Files:**
- Modify: `tests/mente/test_agent_runtime_admin.py`
- Modify: `tests/gateway/test_status_command.py`
- Modify: `tests/hermes_cli/test_web_server.py`

**Step 1: Write the failing tests**
- Add inventory tests for listing all agents with soul/runtime/session metadata.
- Add `/agents` command coverage for richer inventory output.
- Add dashboard API coverage for `GET /api/agents`, `GET /api/agents/{id}`, and runtime actions.

**Step 2: Run test to verify it fails**

Run: `source .venv/bin/activate && scripts/run_tests.sh tests/mente/test_agent_runtime_admin.py tests/gateway/test_status_command.py tests/hermes_cli/test_web_server.py -q`

Expected: FAIL because the inventory API and richer `/agents` output do not exist yet.

### Task 2: Implement shared agent inventory backend

**Files:**
- Modify: `mente/agent_runtime_admin.py`
- Modify: `gateway/run.py`
- Modify: `cli.py`
- Modify: `hermes_cli/web_server.py`

**Step 1: Write minimal implementation**
- Add agent inventory/list/detail helpers on top of the existing runtime admin module.
- Expand `/agents` to show registered agents plus runtime/soul/session state.
- Add dashboard endpoints for listing/detailing agents and invoking runtime reset/clear actions.

**Step 2: Run backend tests**

Run: `source .venv/bin/activate && scripts/run_tests.sh tests/mente/test_agent_runtime_admin.py tests/gateway/test_status_command.py tests/hermes_cli/test_web_server.py -q`

Expected: PASS

### Task 3: Add the dashboard page

**Files:**
- Modify: `web/src/App.tsx`
- Modify: `web/src/lib/api.ts`
- Modify: `web/src/lib/resolve-page-title.ts`
- Modify: `web/src/i18n/types.ts`
- Modify: `web/src/i18n/en.ts`
- Modify: `web/src/i18n/zh.ts`
- Create: `web/src/pages/AgentsPage.tsx`

**Step 1: Build the page**
- Add a new `Agents` nav item and route.
- Render a dedicated operator-facing page with overview cards, per-agent detail, soul preview, runtime health, sessions, and action buttons.
- Reuse the new backend endpoints instead of duplicating logic in the browser.

**Step 2: Run frontend verification**

Run: `cd web && npm run build`

Expected: PASS

### Task 4: Broader verification

**Files:**
- Verify only

**Step 1: Run combined regression**

Run: `source .venv/bin/activate && scripts/run_tests.sh tests/mente/test_agent_runtime_admin.py tests/mente/test_runtime_config.py tests/gateway/test_status_command.py tests/hermes_cli/test_web_server.py -q`

Expected: PASS
