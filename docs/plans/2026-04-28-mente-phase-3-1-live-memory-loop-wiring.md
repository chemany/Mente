# Phase 3.1: Live Memory Loop Wiring Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Wire the already-built Mente memory components into the real runtime so gateway and cron tasks can retrieve prior memories before execution and persist new memories after execution.

**Architecture:** This slice does not add new memory primitives. It only connects existing `MemoryRepository`, `MemoryPromoter`, `ContextBuilder`, and replayable `Orchestrator` flow into the default Hermes bridge path. The success condition is a live two-run loop: run 1 emits a memory candidate, run 2 of the same scope receives that memory via `ExecutionRequest.memory_facts`.

**Tech Stack:** Python 3.11+, pytest, existing `mente` runtime, Hermes bridge integration, SQLite-backed Mente persistence

---

## Scope

This plan is intentionally narrow:

- wire memory retrieval into the default live orchestrator stack
- wire memory promotion into the live post-execution path
- prove the loop with end-to-end tests at the bridge/orchestrator boundary

Explicitly out of scope:

- `/api/debug/memories`
- dashboard memory pages
- retention/forgetting
- semantic search
- ranking beyond current deterministic rules

## Task 1: Extend Orchestrator To Persist Promoted Memory

**Files:**
- Modify: `mente/orchestrator/service.py`
- Modify: `tests/mente/test_orchestrator_service.py`

**Step 1: Write the failing test**

Add a regression test proving that when the executor returns `memory_candidates`, the orchestrator persists them through a provided memory repository without changing the task success outcome.

```python
from mente.context_builder.builder import ContextBuilder
from mente.executors.base import Executor
from mente.memory.promoter import MemoryPromoter
from mente.memory.repository import InMemoryMemoryRepository
from mente.orchestrator.service import Orchestrator
from mente.task_core.models import ExecutionResult, Task
from mente.task_core.repository import InMemoryTaskRepository


class _ExecutorWithMemory(Executor):
    def execute(self, request):
        return ExecutionResult(
            status="success",
            summary="ok",
            memory_candidates=["Repository uses uv for Python commands."],
        )


def test_orchestrator_persists_promoted_memory():
    task_repo = InMemoryTaskRepository()
    memory_repo = InMemoryMemoryRepository()
    orchestrator = Orchestrator(
        repository=task_repo,
        context_builder=ContextBuilder(),
        executor=_ExecutorWithMemory(),
        memory_repository=memory_repo,
        memory_promoter=MemoryPromoter(),
    )
    task = Task(
        task_id="task_1",
        session_id="session_1",
        task_type="engineering",
        objective="Inspect repo",
        user_request="Inspect repo",
        metadata={"source": "gateway"},
    )
    result = orchestrator.run(task)
    assert result.status == "success"
    rows = memory_repo.list_relevant(session_id="session_1", task_type="engineering", limit=5)
    assert [row.fact for row in rows] == ["Repository uses uv for Python commands."]
```

**Step 2: Run test to verify it fails**

Run: `uv run --extra dev pytest tests/mente/test_orchestrator_service.py -v`
Expected: `Orchestrator` does not yet persist promoted memory or lacks memory dependencies

**Step 3: Write minimal implementation**

Extend `Orchestrator.__init__` to accept:

- `memory_repository=None`
- `memory_promoter=None`

Inside `run(...)`:

- execute task normally
- if both dependencies are present, call `memory_promoter.persist(task, result, memory_repository)`
- set `result.metadata["promoted_memory_count"]`
- log promotion failures and continue

Do not flip a successful task to failed if memory persistence breaks.

**Step 4: Run test to verify it passes**

Run: `uv run --extra dev pytest tests/mente/test_orchestrator_service.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add mente/orchestrator/service.py tests/mente/test_orchestrator_service.py
git commit -m "feat: persist promoted memory in orchestrator"
```

## Task 2: Thread Memory Repository Into ContextBuilder In Live Wiring

**Files:**
- Modify: `mente/context_builder/builder.py`
- Modify: `tests/mente/test_context_builder.py`

**Step 1: Write the failing test**

Add a regression test that proves retrieved memory is injected before task-local memory facts and stays deterministic.

```python
from mente.context_builder.builder import ContextBuilder
from mente.memory.models import MemoryRecord
from mente.memory.repository import InMemoryMemoryRepository
from mente.task_core.models import Task


def test_context_builder_prepends_retrieved_memory():
    memory_repo = InMemoryMemoryRepository()
    memory_repo.save(MemoryRecord(
        memory_id="mem_1",
        session_id="session_1",
        task_id="task_old",
        task_type="conversation",
        source="gateway",
        scope="session",
        fact="User prefers concise replies.",
    ))
    task = Task(
        task_id="task_1",
        session_id="session_1",
        task_type="conversation",
        objective="Reply",
        user_request="Reply",
        memory_facts=["Session context: existing"],
    )
    request = ContextBuilder(memory_repository=memory_repo, memory_limit=5).build(task)
    assert request.memory_facts == [
        "Memory: User prefers concise replies.",
        "Session context: existing",
    ]
```

**Step 2: Run test to verify it fails**

Run: `uv run --extra dev pytest tests/mente/test_context_builder.py -v`
Expected: live `ContextBuilder` path does not yet inject repository-backed memory as expected

**Step 3: Write minimal implementation**

If not already completed in the previous Phase 3 session, ensure `ContextBuilder`:

- accepts `memory_repository` and `memory_limit`
- reads `list_relevant(session_id=..., task_type=..., limit=...)`
- formats each injected fact exactly as `Memory: <fact>`
- prepends retrieved facts ahead of `task.memory_facts`
- deduplicates exact duplicate strings

Do not include scores, ids, timestamps, or metadata in prompt-facing memory strings.

**Step 4: Run test to verify it passes**

Run: `uv run --extra dev pytest tests/mente/test_context_builder.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add mente/context_builder/builder.py tests/mente/test_context_builder.py
git commit -m "feat: inject retrieved memory in live context builder"
```

## Task 3: Wire The Default Hermes Bridge To Use Memory Dependencies

**Files:**
- Modify: `mente/integrations/hermes.py`
- Modify: `tests/mente/test_hermes_integration.py`

**Step 1: Write the failing test**

Add a bridge test that proves the default live orchestrator stack includes memory wiring.

```python
from mente.integrations import hermes as hermes_bridge


def test_build_orchestrator_includes_memory_stack(monkeypatch):
    captured = {}

    class _FakeOrchestrator:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(hermes_bridge, "Orchestrator", _FakeOrchestrator)

    hermes_bridge._build_orchestrator(".", repository=object())

    assert captured["memory_repository"] is not None
    assert captured["memory_promoter"] is not None
    assert captured["context_builder"] is not None
```

**Step 2: Run test to verify it fails**

Run: `uv run --extra dev pytest tests/mente/test_hermes_integration.py -v`
Expected: bridge default stack lacks memory repository/promoter wiring

**Step 3: Write minimal implementation**

Update `mente.integrations.hermes`:

- construct a `SQLiteMemoryRepository()` per live run
- pass it into `ContextBuilder(memory_repository=..., memory_limit=5)`
- pass `memory_repository` and `MemoryPromoter()` into `Orchestrator`
- close the memory repository alongside the task repository in `_run_task(...)`

Keep task repository and memory repository as separate objects.

**Step 4: Run test to verify it passes**

Run: `uv run --extra dev pytest tests/mente/test_hermes_integration.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add mente/integrations/hermes.py tests/mente/test_hermes_integration.py
git commit -m "feat: wire memory stack into hermes bridge"
```

## Task 4: Prove The Two-Run Live Memory Loop

**Files:**
- Modify: `tests/mente/test_hermes_integration.py`

**Step 1: Write the failing test**

Add an end-to-end bridge-level test with a fake executor:

- run 1 returns a `memory_candidate`
- run 2 on the same session/task type should receive that memory in `request.memory_facts`

```python
from mente.context_builder.builder import ContextBuilder
from mente.memory.repository import SQLiteMemoryRepository
from mente.orchestrator.service import Orchestrator
from mente.task_core.models import ExecutionResult


def test_second_run_receives_first_run_memory(monkeypatch, tmp_path):
    seen_requests = []

    class _FakeExecutor:
        def execute(self, request):
            seen_requests.append(request)
            if len(seen_requests) == 1:
                return ExecutionResult(
                    status="success",
                    summary="first",
                    memory_candidates=["User prefers concise replies."],
                )
            return ExecutionResult(status="success", summary="second")

    # Patch bridge repositories to use tmp sqlite dbs, then run twice.
    ...
    assert "Memory: User prefers concise replies." in seen_requests[1].memory_facts
```

**Step 2: Run test to verify it fails**

Run: `uv run --extra dev pytest tests/mente/test_hermes_integration.py -k second_run_receives_first_run_memory -v`
Expected: second run does not yet receive first-run memory

**Step 3: Write minimal implementation**

Use the existing bridge helpers and repository patch points to:

- run two tasks through the same live memory DB
- assert run 2 sees run 1 promoted memory
- keep the test narrow and deterministic

Do not invoke the real Codex CLI in this test.

**Step 4: Run test to verify it passes**

Run: `uv run --extra dev pytest tests/mente/test_hermes_integration.py -k second_run_receives_first_run_memory -v`
Expected: PASS

**Step 5: Commit**

```bash
git add tests/mente/test_hermes_integration.py
git commit -m "test: prove live mente memory loop across runs"
```

## Task 5: Run Verification For The Wiring Slice

**Files:**
- No code changes required unless tests fail

**Step 1: Run targeted tests**

Run:

```bash
uv run --extra dev pytest \
  tests/mente/test_memory_models.py \
  tests/mente/test_memory_repository.py \
  tests/mente/test_memory_promoter.py \
  tests/mente/test_context_builder.py \
  tests/mente/test_orchestrator_service.py \
  tests/mente/test_hermes_integration.py \
  tests/mente/test_replay_harness.py \
  tests/mente/test_replay_cli.py -v
```

Expected: PASS

**Step 2: Run adjacent regressions**

Run:

```bash
uv run --extra dev pytest \
  tests/mente/test_codex_executor.py \
  tests/mente/test_task_repository.py \
  tests/gateway/test_api_server_tasks.py \
  tests/hermes_cli/test_mente_oneshot.py -v
```

Expected: PASS

**Step 3: Run compile verification**

Run:

```bash
uv run python -m compileall \
  mente/memory \
  mente/context_builder/builder.py \
  mente/orchestrator/service.py \
  mente/integrations/hermes.py
```

Expected: exit code `0`

**Step 4: Commit final integration**

```bash
git add mente tests docs
git commit -m "feat: wire live mente memory loop"
```

## Acceptance Criteria

This slice is complete when:

- live Mente runs use repository-backed memory retrieval before execution
- live Mente runs promote executor memory candidates after execution
- memory promotion does not break successful task completion on failure
- a two-run bridge/orchestrator test proves run 2 receives run 1 memory
- no new nondeterministic prompt fields are added to prompt-facing memory facts

## Follow-On Work

1. Add `/api/debug/memories` for inspection.
2. Add memory retention/forgetting policy.
3. Extend replay fixtures to assert promoted memory and injected memory explicitly.
4. Add a small Codex-backed smoke replay suite for real executor validation.
