# TUI Mente Codex Unification Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Route TUI conversation execution through Mente's `CodexExecutor` so `gateway`, `oneshot`, and `tui` all share the same Mente-owned execution chain.

**Architecture:** Keep the TUI JSON-RPC/session shell intact, but replace the turn-execution path with a Mente bridge entrypoint dedicated to `tui`. Add a small TUI-facing adapter that preserves the session object shape, continuity metadata, and interrupt/event semantics expected by `tui_gateway/server.py`.

**Tech Stack:** Python, `tui_gateway/server.py`, `mente.integrations.bridge`, `mente.executors.codex`, pytest

---

### Task 1: Add failing bridge coverage for TUI execution

**Files:**
- Modify: `tests/tui_gateway/test_make_agent_provider.py`
- Create: `tests/tui_gateway/test_mente_tui_bridge.py`

**Step 1: Write failing tests**

- Assert TUI conversation routing uses a Mente bridge helper instead of `AIAgent.run_conversation()`.
- Assert the TUI bridge builds `Task.metadata.source == "tui"` and forwards session continuity.
- Assert TUI interrupt can target an active Mente-backed turn.

**Step 2: Run test to verify it fails**

Run: `scripts/run_tests.sh tests/tui_gateway/test_make_agent_provider.py tests/tui_gateway/test_mente_tui_bridge.py -v`

**Step 3: Implement minimal bridge/adapter code**

- Add `build_tui_task()` / `run_tui_task()` to `mente.integrations.bridge`
- Add a TUI-facing adapter in `tui_gateway/server.py`

**Step 4: Run test to verify it passes**

Run: `scripts/run_tests.sh tests/tui_gateway/test_make_agent_provider.py tests/tui_gateway/test_mente_tui_bridge.py -v`

### Task 2: Switch TUI prompt execution to the Mente bridge

**Files:**
- Modify: `tui_gateway/server.py`
- Test: `tests/tui_gateway/test_mente_tui_bridge.py`

**Step 1: Write failing test**

- Assert `prompt.submit` uses the Mente-backed adapter and persists assistant output/history from the returned `ExecutionResult`.

**Step 2: Run test to verify it fails**

Run: `scripts/run_tests.sh tests/tui_gateway/test_mente_tui_bridge.py -k prompt_submit -v`

**Step 3: Write minimal implementation**

- Replace the live-turn path from `agent.run_conversation()` to the TUI adapter
- Preserve `message.start`, `message.complete`, usage payloads, and history persistence
- Map Mente execution events into TUI tool/activity events

**Step 4: Run test to verify it passes**

Run: `scripts/run_tests.sh tests/tui_gateway/test_mente_tui_bridge.py -k prompt_submit -v`

### Task 3: Preserve interactive controls and runtime metadata

**Files:**
- Modify: `tui_gateway/server.py`
- Modify: `mente/integrations/bridge.py`
- Test: `tests/tui_gateway/test_mente_tui_bridge.py`

**Step 1: Write failing test**

- Assert session resume/start maps to `ExecutionMode` / `ExecutionSession`
- Assert `session.interrupt` reaches the active Mente-backed turn controller
- Assert `session.info` still exposes model/runtime metadata expected by the TUI

**Step 2: Run test to verify it fails**

Run: `scripts/run_tests.sh tests/tui_gateway/test_mente_tui_bridge.py -k 'continuity or interrupt or session_info' -v`

**Step 3: Write minimal implementation**

- Add session-scoped active turn bookkeeping for Mente-backed execution
- Expose a lightweight agent facade or compatible metadata surface
- Keep existing slash/config hooks working against the TUI session object

**Step 4: Run test to verify it passes**

Run: `scripts/run_tests.sh tests/tui_gateway/test_mente_tui_bridge.py -k 'continuity or interrupt or session_info' -v`

### Task 4: Verify the unified entrypoints

**Files:**
- Modify: `tests/tui_gateway/test_make_agent_provider.py`
- Modify: `tests/mente/test_bridge_integration.py`
- Modify: `tests/mente/test_hermes_integration.py`

**Step 1: Run targeted verification**

Run: `scripts/run_tests.sh tests/tui_gateway/test_make_agent_provider.py tests/tui_gateway/test_mente_tui_bridge.py tests/mente/test_bridge_integration.py tests/mente/test_hermes_integration.py -v`

**Step 2: Run any focused follow-up if failures indicate contract drift**

Run: `scripts/run_tests.sh <failing-test-node> -v`

**Step 3: Commit**

```bash
git add tui_gateway/server.py mente/integrations/bridge.py tests/tui_gateway/test_make_agent_provider.py tests/tui_gateway/test_mente_tui_bridge.py docs/plans/2026-05-07-tui-mente-codex-unification.md
git commit -m "feat: route tui through mente codex executor"
```
