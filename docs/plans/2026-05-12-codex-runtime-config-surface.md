# Codex Runtime Config Surface Implementation Plan

> **For Mente:** REQUIRED SKILL: Use `executing-plans` to implement this plan task-by-task.

**Goal:** Formalize Mente-owned Codex runtime settings under `config.yaml`'s `codex:` namespace, including request-profile overrides for `content_publishing` and `config_admin`.

**Architecture:** Reuse the existing private Codex config loader so profile and workspace `config.yaml` files remain the source of truth. Keep Mente-owned profile overrides out of the upstream Codex CLI override stream by normalizing them inside `mente/executors/runtime_config.py`.

**Tech Stack:** Python, PyYAML, pytest

---

### Task 1: Lock the desired config surface with tests

**Files:**
- Modify: `tests/mente/test_runtime_config.py`
- Modify: `tests/hermes_cli/test_config_validation.py`

**Step 1: Write the failing tests**

- Add a runtime-config test proving `codex.profiles.content_publishing` and `codex.profiles.config_admin` in `config.yaml` override the hard-coded defaults.
- Add a runtime-config test proving `codex.profiles` is consumed by Mente and not flattened into Codex CLI `-c` overrides.
- Add a config-validation test proving root-level `codex:` is accepted in `config.yaml`.

**Step 2: Run tests to verify they fail**

Run: `scripts/run_tests.sh tests/mente/test_runtime_config.py tests/hermes_cli/test_config_validation.py`

Expected: failures because `codex` is not yet validated as a known root key and profile overrides are not yet normalized out of runtime config.

### Task 2: Implement runtime-config normalization

**Files:**
- Modify: `mente/executors/runtime_config.py`
- Modify: `hermes_cli/config.py`

**Step 1: Write minimal implementation**

- Extend runtime config normalization to extract a Mente-owned `profiles` block from `codex:`.
- Apply per-request overrides from `codex.profiles.content_publishing` and `codex.profiles.config_admin`.
- Preserve existing precedence rules for explicit `base_instructions` and runtime defaults.
- Add `codex` to config validation's known root keys so `config.yaml` no longer warns on the supported namespace.

**Step 2: Run tests to verify they pass**

Run: `scripts/run_tests.sh tests/mente/test_runtime_config.py tests/hermes_cli/test_config_validation.py`

Expected: PASS

### Task 3: Verify the touched Mente execution path stays green

**Files:**
- Test: `tests/mente/test_codex_executor.py`

**Step 1: Run focused integration coverage**

Run: `scripts/run_tests.sh tests/mente/test_codex_executor.py tests/mente/test_runtime_config.py tests/hermes_cli/test_config_validation.py`

Expected: PASS
