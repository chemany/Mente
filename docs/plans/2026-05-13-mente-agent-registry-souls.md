# Mente Agent Registry Soul Storage Implementation Plan

> **For Mente:** REQUIRED SKILL: Use `executing-plans` to implement this plan task-by-task.

**Goal:** Replace flat lane Soul overrides with an agent-centric `MENTE_HOME/agents/registry.yaml` plus per-agent `agent.yaml` and `soul.md` directories, using modern org names and preserving per-request reload behavior.

**Architecture:** Runtime soul resolution will map lane or task-profile to an agent id through a registry, then load `soul.md` from that agent directory. If `MENTE_HOME/agents` is missing, the runtime will auto-seed it from built-in defaults and migrate any existing legacy `MENTE_HOME/souls/*.md` overrides into the mapped agent directories without breaking current behavior.

**Tech Stack:** Python, PyYAML, pathlib, pytest via `scripts/run_tests.sh`

---

### Task 1: Red tests for agent-registry soul loading

**Files:**
- Modify: `tests/mente/test_runtime_config.py`

**Step 1: Write the failing tests**

Add tests that lock these behaviors:
- first runtime access seeds `MENTE_HOME/agents/registry.yaml` plus agent directories for the modern org names;
- `director`/`research`/`content_publishing` resolve Souls from `agents/<agent_id>/soul.md` instead of `souls/<lane>.md`;
- changing `agents/<agent_id>/soul.md` between requests is reflected without recreating the executor;
- legacy `MENTE_HOME/souls/<lane>.md` still overrides by being migrated/bridged into the corresponding agent soul path.

**Step 2: Run tests to verify they fail**

Run:
```bash
source .venv/bin/activate && scripts/run_tests.sh tests/mente/test_runtime_config.py -q
```

Expected: failures showing runtime still reads `MENTE_HOME/souls/*.md` directly and does not seed `MENTE_HOME/agents`.

### Task 2: Runtime registry loader and compatibility bridge

**Files:**
- Modify: `mente/executors/runtime_config.py`
- Test: `tests/mente/test_runtime_config.py`

**Step 1: Write minimal implementation**

Add registry-backed runtime helpers that:
- load built-in agent registry metadata;
- seed `MENTE_HOME/agents/registry.yaml`, `agent.yaml`, and `soul.md` files if absent;
- map lane/task-profile to agent id using registry entries;
- load Soul text from `MENTE_HOME/agents/<agent_id>/soul.md` on every request;
- preserve explicit `codex.base_instructions` hard override;
- support legacy `MENTE_HOME/souls/*.md` by copying/using those values for the mapped agent override path.

**Step 2: Run focused tests**

Run:
```bash
source .venv/bin/activate && scripts/run_tests.sh tests/mente/test_runtime_config.py -q
```

Expected: runtime-config soul tests pass.

### Task 3: Built-in agent registry assets and regression verification

**Files:**
- Create: `mente/agents/registry.yaml`
- Create: `mente/agents/<agent>/agent.yaml`
- Create: `mente/agents/<agent>/soul.md`
- Test: `tests/mente/test_runtime_config.py`
- Test: `tests/mente/test_codex_executor.py`
- Test: `tests/mente/test_bridge_integration.py`
- Test: `tests/tui_gateway/test_mente_tui_bridge.py`

**Step 1: Add built-in defaults**

Create built-in default assets for:
- `executive_office`
- `product_engineering`
- `strategy_research`
- `editorial`
- `platform_operations`
- `publishing_operations`

Each gets `agent.yaml` and `soul.md`, and the registry binds lanes/task-profiles to them.

**Step 2: Run targeted regression suite**

Run:
```bash
source .venv/bin/activate && scripts/run_tests.sh tests/mente/test_runtime_config.py tests/mente/test_codex_executor.py tests/mente/test_bridge_integration.py tests/tui_gateway/test_mente_tui_bridge.py -q
```

Expected: lane routing and prompt selection still work after switching Soul storage to agent directories.
