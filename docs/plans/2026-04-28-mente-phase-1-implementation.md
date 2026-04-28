# Mente Phase 1 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build the first production slice of `Mente` inside a Hermes fork by introducing a schema-driven task runtime and a `CodexExecutor`, then wire one-shot CLI execution through the new path.

**Architecture:** Phase 1 does not replace Hermes wholesale. It adds a parallel runtime under a new `mente` namespace, defines stable task and execution contracts, and integrates only the one-shot CLI path first. This keeps the gateway, cron, memory plugins, and legacy agent loop intact while creating a real cutover path toward Codex-backed execution.

**Tech Stack:** Python 3.11+, Hermes fork, Pydantic 2, pytest, existing Hermes CLI/runtime infrastructure, external Codex CLI invocation

---

## Preconditions

This plan assumes the working repository is a real fork of `hermes-agent`, not the current planning-only workspace. All file paths below are relative to the future Hermes fork root.

## Task 1: Create The Mente Runtime Namespace

**Files:**
- Create: `mente/__init__.py`
- Create: `mente/task_core/__init__.py`
- Create: `mente/orchestrator/__init__.py`
- Create: `mente/context_builder/__init__.py`
- Create: `mente/executors/__init__.py`
- Create: `tests/mente/test_imports.py`

**Step 1: Write the failing test**

```python
def test_mente_namespace_imports():
    import mente
    import mente.task_core
    import mente.orchestrator
    import mente.context_builder
    import mente.executors
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/mente/test_imports.py -v`
Expected: `ModuleNotFoundError` for `mente`

**Step 3: Write minimal implementation**

Create package marker files with minimal module docstrings.

**Step 4: Run test to verify it passes**

Run: `pytest tests/mente/test_imports.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add mente tests/mente/test_imports.py
git commit -m "feat: add mente runtime namespace"
```

## Task 2: Define Core Task Schemas

**Files:**
- Create: `mente/task_core/models.py`
- Create: `tests/mente/test_task_models.py`

**Step 1: Write the failing test**

```python
from mente.task_core.models import Task, TaskStatus, ExecutionRequest, ExecutionResult


def test_task_defaults():
    task = Task(
        task_id="task_123",
        session_id="session_123",
        task_type="engineering",
        objective="Update a config file",
        user_request="change config",
    )
    assert task.status == TaskStatus.INGESTED
    assert task.acceptance_criteria == []


def test_execution_result_success_shape():
    result = ExecutionResult(
        status="success",
        summary="done",
        actions_taken=["edited config"],
        changed_files=["config.yaml"],
    )
    assert result.status == "success"
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/mente/test_task_models.py -v`
Expected: import failure for `mente.task_core.models`

**Step 3: Write minimal implementation**

Implement Pydantic models and enums for:

- `TaskStatus`
- `Task`
- `ExecutionRequest`
- `ExecutionResult`

Include fields defined in the design doc and sensible defaults for list fields.

**Step 4: Run test to verify it passes**

Run: `pytest tests/mente/test_task_models.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add mente/task_core/models.py tests/mente/test_task_models.py
git commit -m "feat: add mente task and execution schemas"
```

## Task 3: Add A Task Repository

**Files:**
- Create: `mente/task_core/repository.py`
- Create: `tests/mente/test_task_repository.py`

**Step 1: Write the failing test**

```python
from mente.task_core.models import Task
from mente.task_core.repository import InMemoryTaskRepository


def test_repository_round_trip():
    repo = InMemoryTaskRepository()
    task = Task(
        task_id="task_1",
        session_id="session_1",
        task_type="engineering",
        objective="Do work",
        user_request="Do work",
    )
    repo.save(task)
    loaded = repo.get("task_1")
    assert loaded is not None
    assert loaded.task_id == "task_1"
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/mente/test_task_repository.py -v`
Expected: import failure for `InMemoryTaskRepository`

**Step 3: Write minimal implementation**

Create:

- `TaskRepository` protocol or abstract base
- `InMemoryTaskRepository`

Keep storage simple for Phase 1. Do not bind to SQLite yet.

**Step 4: Run test to verify it passes**

Run: `pytest tests/mente/test_task_repository.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add mente/task_core/repository.py tests/mente/test_task_repository.py
git commit -m "feat: add mente task repository"
```

## Task 4: Add The Executor Interface

**Files:**
- Create: `mente/executors/base.py`
- Create: `tests/mente/test_executor_base.py`

**Step 1: Write the failing test**

```python
from mente.executors.base import Executor


def test_executor_subclass_contract():
    class _FakeExecutor(Executor):
        def execute(self, request):
            return None

    executor = _FakeExecutor()
    assert executor is not None
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/mente/test_executor_base.py -v`
Expected: import failure for `Executor`

**Step 3: Write minimal implementation**

Define an executor contract that accepts `ExecutionRequest` and returns `ExecutionResult`.

**Step 4: Run test to verify it passes**

Run: `pytest tests/mente/test_executor_base.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add mente/executors/base.py tests/mente/test_executor_base.py
git commit -m "feat: add executor interface"
```

## Task 5: Implement A Minimal CodexExecutor

**Files:**
- Create: `mente/executors/codex.py`
- Create: `tests/mente/test_codex_executor.py`

**Step 1: Write the failing test**

```python
from mente.executors.codex import CodexExecutor
from mente.task_core.models import ExecutionRequest


def test_codex_executor_builds_command():
    executor = CodexExecutor(codex_binary="codex")
    request = ExecutionRequest(
        task_id="task_1",
        session_id="session_1",
        task_type="engineering",
        objective="Inspect repository",
        user_request="inspect repository",
        workspace=".",
    )
    cmd = executor.build_command(request)
    assert cmd[0] == "codex"
    assert any("Inspect repository" in part for part in cmd)
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/mente/test_codex_executor.py -v`
Expected: import failure for `CodexExecutor`

**Step 3: Write minimal implementation**

Implement:

- `CodexExecutor.__init__`
- `CodexExecutor.build_prompt`
- `CodexExecutor.build_command`
- `CodexExecutor.execute`

Phase 1 behavior:

- shell out to the Codex CLI
- pass a stable prompt assembled from `ExecutionRequest`
- capture stdout and stderr
- return a basic `ExecutionResult`

Do not implement resume, streaming, or artifact extraction yet.

**Step 4: Run test to verify it passes**

Run: `pytest tests/mente/test_codex_executor.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add mente/executors/codex.py tests/mente/test_codex_executor.py
git commit -m "feat: add minimal codex executor"
```

## Task 6: Add The Context Builder

**Files:**
- Create: `mente/context_builder/builder.py`
- Create: `tests/mente/test_context_builder.py`

**Step 1: Write the failing test**

```python
from mente.context_builder.builder import ContextBuilder
from mente.task_core.models import Task


def test_context_builder_produces_execution_request():
    builder = ContextBuilder()
    task = Task(
        task_id="task_1",
        session_id="session_1",
        task_type="engineering",
        objective="Inspect repository",
        user_request="Inspect repository",
    )
    request = builder.build(task)
    assert request.task_id == "task_1"
    assert request.objective == "Inspect repository"
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/mente/test_context_builder.py -v`
Expected: import failure for `ContextBuilder`

**Step 3: Write minimal implementation**

Build a deterministic `ExecutionRequest` from a `Task`.

Include placeholder hooks for:

- memory facts
- skill refs
- acceptance criteria
- workspace

Keep ordering deterministic.

**Step 4: Run test to verify it passes**

Run: `pytest tests/mente/test_context_builder.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add mente/context_builder/builder.py tests/mente/test_context_builder.py
git commit -m "feat: add deterministic context builder"
```

## Task 7: Add The Orchestrator Service

**Files:**
- Create: `mente/orchestrator/service.py`
- Create: `tests/mente/test_orchestrator_service.py`

**Step 1: Write the failing test**

```python
from mente.context_builder.builder import ContextBuilder
from mente.executors.base import Executor
from mente.orchestrator.service import Orchestrator
from mente.task_core.models import ExecutionResult, Task
from mente.task_core.repository import InMemoryTaskRepository


class _FakeExecutor(Executor):
    def execute(self, request):
        return ExecutionResult(status="success", summary="ok")


def test_orchestrator_runs_task():
    orchestrator = Orchestrator(
        repository=InMemoryTaskRepository(),
        context_builder=ContextBuilder(),
        executor=_FakeExecutor(),
    )
    task = Task(
        task_id="task_1",
        session_id="session_1",
        task_type="engineering",
        objective="Do work",
        user_request="Do work",
    )
    result = orchestrator.run(task)
    assert result.status == "success"
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/mente/test_orchestrator_service.py -v`
Expected: import failure for `Orchestrator`

**Step 3: Write minimal implementation**

Implement:

- task persistence on ingest
- task status transitions through `plan`, `prepare_context`, `execute`, and `persist`
- executor invocation
- final task status update

Keep planning minimal in Phase 1. It can be rule-based.

**Step 4: Run test to verify it passes**

Run: `pytest tests/mente/test_orchestrator_service.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add mente/orchestrator/service.py tests/mente/test_orchestrator_service.py
git commit -m "feat: add mente orchestrator"
```

## Task 8: Add CLI One-Shot Integration

**Files:**
- Modify: `hermes_cli/oneshot.py`
- Modify: `hermes_cli/main.py`
- Create: `tests/hermes_cli/test_mente_oneshot.py`

**Step 1: Write the failing test**

```python
from hermes_cli.oneshot import run_oneshot


def test_run_oneshot_routes_through_mente(monkeypatch, capsys):
    monkeypatch.setenv("HERMES_ONESHOT_EXECUTOR", "mente")
    monkeypatch.setattr(
        "hermes_cli.oneshot._run_mente",
        lambda prompt, model=None, provider=None: "via mente",
    )
    rc = run_oneshot("inspect repo")
    captured = capsys.readouterr()
    assert rc == 0
    assert captured.out == "via mente\n"
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/hermes_cli/test_mente_oneshot.py -v`
Expected: FAIL because `hermes_cli.oneshot` does not yet define `_run_mente` or route on `HERMES_ONESHOT_EXECUTOR`

**Step 3: Write minimal implementation**

Add a Phase 1 route switch in `hermes_cli/oneshot.py`. The lowest-risk version is an environment gate such as `HERMES_ONESHOT_EXECUTOR=mente`, with an optional CLI flag added later in `hermes_cli/main.py`.

Expected behavior:

- `run_oneshot()` selects `_run_mente()` when the route is enabled
- `_run_mente()` creates a `Task`
- `_run_mente()` builds an `ExecutionRequest`
- `_run_mente()` calls `CodexExecutor`
- render the returned `ExecutionResult.summary`

Do not route the interactive TUI, gateway, or cron through the new runtime yet.

**Step 4: Run test to verify it passes**

Run: `pytest tests/hermes_cli/test_mente_oneshot.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add hermes_cli/oneshot.py hermes_cli/main.py tests/hermes_cli/test_mente_oneshot.py
git commit -m "feat: wire oneshot cli through mente executor"
```

## Task 9: Add Basic Observability And Failure Mapping

**Files:**
- Modify: `mente/executors/codex.py`
- Modify: `mente/orchestrator/service.py`
- Create: `tests/mente/test_failure_mapping.py`

**Step 1: Write the failing test**

```python
from mente.task_core.models import ExecutionResult


def test_failed_execution_result_preserves_reason():
    result = ExecutionResult(status="failed", summary="failed", failure_reason="timeout")
    assert result.failure_reason == "timeout"
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/mente/test_failure_mapping.py -v`
Expected: fail if `failure_reason` is not yet modeled or persisted correctly

**Step 3: Write minimal implementation**

Ensure:

- subprocess failures map to structured `ExecutionResult`
- orchestrator stores final failed state
- basic logging exists for task ID, workspace, and executor exit status

**Step 4: Run test to verify it passes**

Run: `pytest tests/mente/test_failure_mapping.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add mente/executors/codex.py mente/orchestrator/service.py tests/mente/test_failure_mapping.py
git commit -m "feat: add execution failure mapping"
```

## Task 10: Run The Phase 1 Verification Suite

**Files:**
- Modify: `docs/plans/2026-04-28-mente-phase-1-implementation.md`

**Step 1: Run targeted tests**

Run:

```bash
pytest tests/mente/test_imports.py \
  tests/mente/test_task_models.py \
  tests/mente/test_task_repository.py \
  tests/mente/test_executor_base.py \
  tests/mente/test_codex_executor.py \
  tests/mente/test_context_builder.py \
  tests/mente/test_orchestrator_service.py \
  tests/mente/test_failure_mapping.py \
  tests/hermes_cli/test_mente_oneshot.py -v
```

Expected: PASS

**Step 2: Run a focused lint or type check if the fork already has one**

Run: `python -m compileall mente`
Expected: no syntax errors

**Step 3: Update the plan with actual progress notes**

Add a short implementation status note at the end of this document after work completes.

**Step 4: Commit**

```bash
git add docs/plans/2026-04-28-mente-phase-1-implementation.md
git commit -m "docs: record mente phase 1 verification status"
```

## Phase 1 Exit Criteria

Phase 1 is complete when:

- a new `mente` runtime namespace exists in the Hermes fork
- task and execution schemas are real code, not just docs
- one-shot CLI requests can route through `CodexExecutor`
- execution returns structured results
- failures produce stable task states
- gateway and cron remain untouched and operational on legacy runtime

## Phase 1 Deliberate Non-Goals

Do not include these in Phase 1:

- full gateway cutover
- cron cutover
- skill evolution rewrite
- memory provider rewrite
- long-lived Codex session resumption
- artifact indexing
- TUI interactive cutover

## Implementation Status

Status recorded on 2026-04-28.

Completed in this phase:

- Added the `mente` runtime namespace and package discovery in `pyproject.toml`
- Added core task schemas in `mente/task_core/models.py`
- Added the in-memory task repository in `mente/task_core/repository.py`
- Added the executor interface in `mente/executors/base.py`
- Added a minimal `CodexExecutor` in `mente/executors/codex.py`
- Added a deterministic `ContextBuilder` in `mente/context_builder/builder.py`
- Added the Phase 1 `Orchestrator` in `mente/orchestrator/service.py`
- Added `HERMES_ONESHOT_EXECUTOR=mente` routing in `hermes_cli/oneshot.py`
- Added structured failure mapping for Codex spawn failures and failed task persistence

Verification run:

```bash
uv run --extra dev pytest tests/mente/test_imports.py \
  tests/mente/test_task_models.py \
  tests/mente/test_task_repository.py \
  tests/mente/test_executor_base.py \
  tests/mente/test_codex_executor.py \
  tests/mente/test_context_builder.py \
  tests/mente/test_orchestrator_service.py \
  tests/mente/test_failure_mapping.py \
  tests/hermes_cli/test_mente_oneshot.py -v

uv run python -m compileall mente
```

Verification outcome:

- `12 passed`
- `compileall` completed without syntax errors

Residual risks after Phase 1:

- `CodexExecutor` is still a minimal synchronous wrapper with no streaming, resume, or artifact indexing
- `oneshot` routing is environment-gated only; no first-class CLI flag or config surface exists yet
- gateway, cron, TUI, and long-lived session flows still run on legacy Hermes paths
