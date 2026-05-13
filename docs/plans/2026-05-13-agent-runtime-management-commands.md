# Agent Runtime Management Commands Implementation Plan

> **For Mente:** REQUIRED SKILL: Use `executing-plans` to implement this plan task-by-task.

**Goal:** Add management commands to inspect one agent's runtime sessions, clear one agent's runtime, and reset one agent's execution context across CLI and gateway.

**Architecture:** Add a reusable `mente.agent_runtime_admin` helper that resolves agent references from the registry and performs runtime inspection/mutation against `MENTE_HOME/runtime/agents/<agent>/codex`. Wire one slash command, `/agent-runtime`, into the central command registry plus both CLI and gateway dispatch paths.

**Tech Stack:** Python, pytest via `scripts/run_tests.sh`, existing Hermes slash-command registry, Mente agent registry/runtime layout.

---

### Task 1: Define failing behavior in tests

**Files:**
- Create: `tests/mente/test_agent_runtime_admin.py`
- Modify: `tests/hermes_cli/test_commands.py`
- Modify: `tests/gateway/test_command_bypass_active_session.py`
- Modify: `tests/gateway/test_status_command.py`

**Step 1: Write the failing tests**
- Add helper tests for agent resolution, session listing, reset semantics, and clear semantics.
- Add command-registry assertions for `/agent-runtime`.
- Add active-session bypass coverage for `/agent-runtime`.
- Add gateway routing coverage for `/agent-runtime`.

**Step 2: Run test to verify it fails**

Run: `source .venv/bin/activate && scripts/run_tests.sh tests/mente/test_agent_runtime_admin.py tests/hermes_cli/test_commands.py tests/gateway/test_command_bypass_active_session.py tests/gateway/test_status_command.py -q`

Expected: FAIL because the helper module and command wiring do not exist yet.

### Task 2: Implement runtime admin helper

**Files:**
- Create: `mente/agent_runtime_admin.py`
- Reuse: `mente/executors/runtime_config.py`

**Step 1: Write minimal implementation**
- Load and seed the Mente agent registry from `MENTE_HOME`.
- Resolve exact ids plus lane/task-profile aliases to an agent.
- Inspect `sessions/`, `state*.sqlite*`, and `logs*.sqlite*`.
- Implement `reset` to remove sessions and sqlite execution state but preserve auth/config.
- Implement `clear` to recreate an empty runtime root.

**Step 2: Run targeted tests**

Run: `source .venv/bin/activate && scripts/run_tests.sh tests/mente/test_agent_runtime_admin.py -q`

Expected: PASS

### Task 3: Wire the slash command

**Files:**
- Modify: `hermes_cli/commands.py`
- Modify: `cli.py`
- Modify: `gateway/run.py`

**Step 1: Add `/agent-runtime [sessions|reset|clear] <agent>`**
- Register command and subcommands centrally.
- Add CLI handler with readable text output.
- Add gateway handler plus running-agent bypass dispatch.

**Step 2: Run focused command tests**

Run: `source .venv/bin/activate && scripts/run_tests.sh tests/hermes_cli/test_commands.py tests/gateway/test_command_bypass_active_session.py tests/gateway/test_status_command.py -q`

Expected: PASS

### Task 4: Run broader regression

**Files:**
- Verify only

**Step 1: Run broader Mente/gateway regression**

Run: `source .venv/bin/activate && scripts/run_tests.sh tests/mente/test_agent_runtime_admin.py tests/mente/test_runtime_config.py tests/mente/test_codex_executor.py tests/gateway/test_command_bypass_active_session.py tests/gateway/test_status_command.py tests/tui_gateway/test_mente_tui_bridge.py -q`

Expected: PASS
