# Mente Multi-Agent Lanes Phase 7 Implementation Plan

> **For Mente:** REQUIRED SKILL: Use `executing-plans` to implement this plan task-by-task.

**Goal:** Give each Mente lane its own Soul source and make every Codex runtime request resolve the current lane Soul dynamically instead of relying on static in-code instruction constants.

**Architecture:** Replace hard-coded lane base-instruction selection with a small Soul loader that resolves built-in defaults from repo files and optional overrides from `MENTE_HOME/souls/`. Keep existing lane/task-profile routing intact, but make `adapt_runtime_config_for_request()` reload the relevant Soul text on every request so changes to a lane Soul take effect immediately without restarting the executor.

**Tech Stack:** Python, pytest via `scripts/run_tests.sh`, Mente runtime-config adaptation, Codex executor request path, file-backed Soul templates

---

### Task 1: Phase-7 failing tests

**Files:**
- Modify: `tests/mente/test_runtime_config.py`

**Step 1: Write the failing tests**

Add tests that lock these behaviors:
- `director`, `engineering`, `research`, `writing`, `config_admin`, and `content_publishing` can source their base instructions from file-backed Souls;
- `MENTE_HOME/souls/<lane>.md` overrides the built-in Soul for that lane;
- changing a Soul file between two `adapt_runtime_config_for_request()` calls is reflected on the second call without recreating the executor/runtime config;
- explicit top-level `codex.base_instructions` still wins as a hard override.

**Step 2: Run tests to verify they fail**

Run:
```bash
source .venv/bin/activate && scripts/run_tests.sh tests/mente/test_runtime_config.py -q
```

Expected: failures showing Souls are still hard-coded constants and runtime adaptation does not re-read lane instructions from files.

### Task 2: Soul loader and runtime adaptation

**Files:**
- Create: `mente/souls/director.md`
- Create: `mente/souls/engineering.md`
- Create: `mente/souls/research.md`
- Create: `mente/souls/writing.md`
- Create: `mente/souls/config_admin.md`
- Create: `mente/souls/content_publishing.md`
- Modify: `mente/executors/runtime_config.py`
- Test: `tests/mente/test_runtime_config.py`

**Step 1: Write minimal implementation**

Add one shared Soul resolution path that:
- reads built-in lane/profile Soul files from the repo;
- prefers `MENTE_HOME/souls/<name>.md` when present;
- maps `content_publishing` and `config_admin` task profiles before generic lane defaults;
- resolves engineering requests through an explicit engineering Soul instead of a purely hard-coded fallback;
- reloads the chosen Soul file on every `adapt_runtime_config_for_request()` call.

**Step 2: Run focused tests**

Run:
```bash
source .venv/bin/activate && scripts/run_tests.sh tests/mente/test_runtime_config.py -q
```

Expected: runtime-config Soul tests pass.

### Task 3: Regression verification

**Files:**
- Test: `tests/mente/test_runtime_config.py`
- Test: `tests/mente/test_codex_executor.py`
- Test: `tests/mente/test_bridge_integration.py`

**Step 1: Run targeted regression suite**

Run:
```bash
source .venv/bin/activate && scripts/run_tests.sh tests/mente/test_runtime_config.py tests/mente/test_codex_executor.py tests/mente/test_bridge_integration.py -q
```

Expected: file-backed Souls do not regress lane prompt selection, gateway/TUI routing, or existing runtime-config behavior.
