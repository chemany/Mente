# Mente Phase 3 Implementation Plan

> **For Mente:** Use `executing-plans` to implement this plan task-by-task.

**Goal:** Add the first durable learning loop to `Mente` by introducing a persistent memory store, deterministic memory promotion and retrieval, and a replay harness that can re-run normalized tasks without going through live gateway or cron ingress.

**Architecture:** Phase 3 keeps `CodexExecutor` stateless. `Mente` becomes the owner of long-term memory and replayable task fixtures. Retrieval happens before execution inside `ContextBuilder`, promotion happens after execution inside `Orchestrator`, and replay runs the exact normalized `Task` envelope through the same orchestration stack with either a mock executor or the real Codex executor. Determinism is a hard requirement: memory injection order, formatting, filtering, and replay fixtures must be stable so prompt shape stays cache-friendly.

**Tech Stack:** Python 3.11+, Pydantic 2, SQLite, pytest, existing `mente` runtime, Hermes test harness, external Codex CLI for optional replay smoke tests

---

## Preconditions

- Use `@test-driven-development` for every task below.
- Do not make `CodexExecutor` itself own persistent memory.
- Do not inject free-form transcripts into long-term memory.
- Keep memory facts deterministic:
  - exact sort order
  - exact prefix format
  - bounded count
  - no timestamps in prompt-facing memory strings
- Do not break existing Phase 1 and Phase 2 behavior when no memory records exist.

## Proposed Data Model

Use a minimal fact-based memory record, not a transcript store.

```python
class MemoryRecord(BaseModel):
    memory_id: str
    session_id: str | None = None
    task_id: str
    task_type: str
    source: str
    scope: str  # "global" | "task_type" | "session"
    fact: str
    kind: str = "fact"
    score: float = 1.0
    created_at: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
```

Retrieval ranking for the first slice should stay simple and deterministic:

1. matching `session` scope
2. matching `task_type` scope
3. matching `global` scope
4. then `score DESC`, `created_at DESC`, `memory_id DESC`

## Task 1: Create The Memory Namespace And Schemas

**Files:**
- Create: `mente/memory/__init__.py`
- Create: `mente/memory/models.py`
- Test: `tests/mente/test_memory_models.py`

**Step 1: Write the failing test**

```python
from mente.memory.models import MemoryRecord


def test_memory_record_defaults():
    record = MemoryRecord(
        memory_id="mem_1",
        task_id="task_1",
        task_type="conversation",
        source="gateway",
        scope="session",
        fact="User prefers concise replies.",
    )
    assert record.kind == "fact"
    assert record.score == 1.0
    assert record.session_id is None
```

**Step 2: Run test to verify it fails**

Run: `uv run --extra dev pytest tests/mente/test_memory_models.py -v`
Expected: import failure for `mente.memory.models`

**Step 3: Write minimal implementation**

Implement `MemoryRecord` in `mente/memory/models.py` with:

- stable scalar fields only
- optional `session_id`
- `metadata` defaulting to `{}`
- `kind="fact"` and `score=1.0`

**Step 4: Run test to verify it passes**

Run: `uv run --extra dev pytest tests/mente/test_memory_models.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add mente/memory tests/mente/test_memory_models.py
git commit -m "feat: add mente memory models"
```

## Task 2: Add A Memory Repository

**Files:**
- Modify: `mente/task_core/repository.py`
- Create: `mente/memory/repository.py`
- Test: `tests/mente/test_memory_repository.py`

**Step 1: Write the failing test**

```python
from mente.memory.models import MemoryRecord
from mente.memory.repository import InMemoryMemoryRepository


def test_memory_repository_round_trip():
    repo = InMemoryMemoryRepository()
    record = MemoryRecord(
        memory_id="mem_1",
        session_id="session_1",
        task_id="task_1",
        task_type="conversation",
        source="gateway",
        scope="session",
        fact="User prefers concise replies.",
    )
    repo.save(record)
    rows = repo.list_relevant(session_id="session_1", task_type="conversation", limit=5)
    assert [row.fact for row in rows] == ["User prefers concise replies."]
```

**Step 2: Run test to verify it fails**

Run: `uv run --extra dev pytest tests/mente/test_memory_repository.py -v`
Expected: import failure for `InMemoryMemoryRepository`

**Step 3: Write minimal implementation**

Create `mente/memory/repository.py` with:

- `MemoryRepository` protocol
- `InMemoryMemoryRepository`
- `SQLiteMemoryRepository`
- `get_default_memory_db_path()` reusing Hermes home like task storage

Add a dedicated SQLite table, not a JSON blob-only store:

```sql
CREATE TABLE IF NOT EXISTS mente_memories (
    memory_id TEXT PRIMARY KEY,
    session_id TEXT,
    task_id TEXT NOT NULL,
    task_type TEXT NOT NULL,
    source TEXT NOT NULL,
    scope TEXT NOT NULL,
    fact TEXT NOT NULL,
    kind TEXT NOT NULL,
    score REAL NOT NULL,
    metadata_json TEXT NOT NULL,
    created_at REAL NOT NULL
);
```

Expose:

- `save(record)`
- `get(memory_id)`
- `list_relevant(session_id, task_type, limit=5, source=None)`

`list_relevant(...)` must:

- prefer `session` scope for matching session
- include matching `task_type` scope
- include `global` scope
- sort deterministically

Do not overload `mente/task_core/repository.py` with memory methods. Keep memory persistence separate.

**Step 4: Run test to verify it passes**

Run: `uv run --extra dev pytest tests/mente/test_memory_repository.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add mente/memory/repository.py tests/mente/test_memory_repository.py
git commit -m "feat: add mente memory repository"
```

## Task 3: Add The MemoryPromoter

**Files:**
- Create: `mente/memory/promoter.py`
- Test: `tests/mente/test_memory_promoter.py`

**Step 1: Write the failing test**

```python
from mente.memory.promoter import MemoryPromoter
from mente.task_core.models import ExecutionResult, Task


def test_memory_promoter_deduplicates_candidates():
    promoter = MemoryPromoter()
    task = Task(
        task_id="task_1",
        session_id="session_1",
        task_type="conversation",
        objective="Reply",
        user_request="Reply",
        metadata={"source": "gateway"},
    )
    result = ExecutionResult(
        status="success",
        summary="done",
        memory_candidates=[
            "User prefers concise replies.",
            " User prefers concise replies. ",
            "",
        ],
    )
    promoted = promoter.extract(task, result)
    assert [row.fact for row in promoted] == ["User prefers concise replies."]
```

**Step 2: Run test to verify it fails**

Run: `uv run --extra dev pytest tests/mente/test_memory_promoter.py -v`
Expected: import failure for `MemoryPromoter`

**Step 3: Write minimal implementation**

Implement `MemoryPromoter` with:

- `normalize_fact(text: str) -> str`
- `extract(task, result) -> list[MemoryRecord]`
- `persist(task, result, repository) -> list[MemoryRecord]`

Rules for the first slice:

- trim whitespace
- collapse internal blank lines
- drop empty strings
- exact-string dedupe after normalization
- cap at `max_promoted_memories_per_run=5`
- derive scope:
  - `conversation` + gateway source -> `session`
  - cron and non-conversation engineering tasks -> `task_type`
- optionally mark `metadata["promotion_reason"] = "executor_memory_candidate"`

Do not ask Codex to classify memory kinds yet. Keep it deterministic and local.

**Step 4: Run test to verify it passes**

Run: `uv run --extra dev pytest tests/mente/test_memory_promoter.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add mente/memory/promoter.py tests/mente/test_memory_promoter.py
git commit -m "feat: add mente memory promoter"
```

## Task 4: Inject Retrieved Memory Into ContextBuilder

**Files:**
- Modify: `mente/context_builder/builder.py`
- Test: `tests/mente/test_context_builder.py`

**Step 1: Write the failing test**

```python
from mente.context_builder.builder import ContextBuilder
from mente.memory.models import MemoryRecord
from mente.memory.repository import InMemoryMemoryRepository
from mente.task_core.models import Task


def test_context_builder_injects_relevant_memory_in_stable_order():
    repo = InMemoryMemoryRepository()
    repo.save(MemoryRecord(
        memory_id="mem_session",
        session_id="session_1",
        task_id="task_old",
        task_type="conversation",
        source="gateway",
        scope="session",
        fact="User prefers concise replies.",
    ))
    builder = ContextBuilder(memory_repository=repo, memory_limit=5)
    task = Task(
        task_id="task_1",
        session_id="session_1",
        task_type="conversation",
        objective="Reply",
        user_request="Reply",
    )
    request = builder.build(task)
    assert request.memory_facts[0] == "Memory: User prefers concise replies."
```

**Step 2: Run test to verify it fails**

Run: `uv run --extra dev pytest tests/mente/test_context_builder.py -v`
Expected: `ContextBuilder.__init__` missing `memory_repository` support or `memory_facts` not injected

**Step 3: Write minimal implementation**

Extend `ContextBuilder` to accept:

- `memory_repository: MemoryRepository | None = None`
- `memory_limit: int = 5`

Implementation rules:

- read `repo.list_relevant(session_id=task.session_id, task_type=task.task_type, limit=memory_limit)`
- convert records into exact prompt-safe strings:

```python
f"Memory: {record.fact}"
```

- prepend retrieved memory ahead of task-provided `task.memory_facts`
- keep deterministic order
- avoid duplicate facts between retrieved memory and `task.memory_facts`

Do not add timestamps, scores, or memory ids to prompt-facing strings.

**Step 4: Run test to verify it passes**

Run: `uv run --extra dev pytest tests/mente/test_context_builder.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add mente/context_builder/builder.py tests/mente/test_context_builder.py
git commit -m "feat: inject mente memory into context builder"
```

## Task 5: Wire Promotion Into Orchestrator

**Files:**
- Modify: `mente/orchestrator/service.py`
- Test: `tests/mente/test_orchestrator_service.py`

**Step 1: Write the failing test**

```python
from mente.context_builder.builder import ContextBuilder
from mente.executors.base import Executor
from mente.memory.promoter import MemoryPromoter
from mente.memory.repository import InMemoryMemoryRepository
from mente.orchestrator.service import Orchestrator
from mente.task_core.models import ExecutionResult, Task
from mente.task_core.repository import InMemoryTaskRepository


class _FakeExecutor(Executor):
    def execute(self, request):
        return ExecutionResult(
            status="success",
            summary="ok",
            memory_candidates=["Repository uses uv for Python commands."],
        )


def test_orchestrator_promotes_memory_after_execution():
    task_repo = InMemoryTaskRepository()
    memory_repo = InMemoryMemoryRepository()
    orchestrator = Orchestrator(
        repository=task_repo,
        context_builder=ContextBuilder(),
        executor=_FakeExecutor(),
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
    orchestrator.run(task)
    facts = memory_repo.list_relevant(session_id="session_1", task_type="engineering", limit=5)
    assert [row.fact for row in facts] == ["Repository uses uv for Python commands."]
```

**Step 2: Run test to verify it fails**

Run: `uv run --extra dev pytest tests/mente/test_orchestrator_service.py -v`
Expected: `Orchestrator` missing memory repository / promoter support

**Step 3: Write minimal implementation**

Extend `Orchestrator.__init__` with:

- `memory_repository: MemoryRepository | None = None`
- `memory_promoter: MemoryPromoter | None = None`

After executor completion and before final task save:

- if both are present, call `memory_promoter.persist(task, result, memory_repository)`
- catch and log promotion errors without failing the task
- store the count in `result.metadata["promoted_memory_count"]`

Do not let memory persistence failure flip a successful executor result to failed.

**Step 4: Run test to verify it passes**

Run: `uv run --extra dev pytest tests/mente/test_orchestrator_service.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add mente/orchestrator/service.py tests/mente/test_orchestrator_service.py
git commit -m "feat: persist promoted memories in orchestrator"
```

## Task 6: Thread Memory Through The Hermes Bridge Defaults

**Files:**
- Modify: `mente/integrations/hermes.py`
- Test: `tests/mente/test_hermes_integration.py`

**Step 1: Write the failing test**

```python
from mente.integrations import hermes as hermes_bridge


def test_bridge_builds_orchestrator_with_memory_stack(monkeypatch):
    captured = {}

    class _FakeOrchestrator:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(hermes_bridge, "Orchestrator", _FakeOrchestrator)
    hermes_bridge._build_orchestrator(".", repository=object())
    assert captured["memory_repository"] is not None
    assert captured["memory_promoter"] is not None
```

**Step 2: Run test to verify it fails**

Run: `uv run --extra dev pytest tests/mente/test_hermes_integration.py -v`
Expected: bridge does not yet construct memory dependencies

**Step 3: Write minimal implementation**

Update bridge defaults so `_build_orchestrator(...)` constructs:

- `ContextBuilder(default_workspace=workspace, memory_repository=memory_repository, memory_limit=5)`
- `MemoryPromoter()`
- `SQLiteMemoryRepository()`

Use one shared memory repository instance per run, then close it in `_run_task(...)` just like the task repository.

Do not couple the task repository and memory repository into one class.

**Step 4: Run test to verify it passes**

Run: `uv run --extra dev pytest tests/mente/test_hermes_integration.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add mente/integrations/hermes.py tests/mente/test_hermes_integration.py
git commit -m "feat: wire mente memory into hermes bridge"
```

## Task 7: Add A Replay Harness Core

**Files:**
- Create: `mente/testing/__init__.py`
- Create: `mente/testing/replay.py`
- Test: `tests/mente/test_replay_harness.py`

**Step 1: Write the failing test**

```python
from mente.context_builder.builder import ContextBuilder
from mente.executors.base import Executor
from mente.memory.repository import InMemoryMemoryRepository
from mente.orchestrator.service import Orchestrator
from mente.task_core.models import ExecutionResult
from mente.task_core.repository import InMemoryTaskRepository
from mente.testing.replay import replay_task


class _FakeExecutor(Executor):
    def execute(self, request):
        return ExecutionResult(status="success", summary=f"ran:{request.task_id}")


def test_replay_task_runs_normalized_fixture():
    result = replay_task(
        fixture={
            "task": {
                "task_id": "task_1",
                "session_id": "session_1",
                "task_type": "conversation",
                "objective": "Reply",
                "user_request": "Reply",
            }
        },
        orchestrator=Orchestrator(
            repository=InMemoryTaskRepository(),
            context_builder=ContextBuilder(memory_repository=InMemoryMemoryRepository()),
            executor=_FakeExecutor(),
        ),
    )
    assert result.summary == "ran:task_1"
```

**Step 2: Run test to verify it fails**

Run: `uv run --extra dev pytest tests/mente/test_replay_harness.py -v`
Expected: import failure for `mente.testing.replay`

**Step 3: Write minimal implementation**

Create `mente/testing/replay.py` with:

- `load_replay_fixture(path) -> dict`
- `replay_task(fixture, orchestrator) -> ExecutionResult`
- `build_task_from_fixture(fixture) -> Task`

Fixture contract for the first slice:

```json
{
  "task": {
    "task_id": "task_1",
    "session_id": "session_1",
    "task_type": "conversation",
    "objective": "Reply",
    "user_request": "Reply",
    "metadata": {"source": "gateway"}
  }
}
```

Do not include executor transcripts in the fixture format yet.

**Step 4: Run test to verify it passes**

Run: `uv run --extra dev pytest tests/mente/test_replay_harness.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add mente/testing tests/mente/test_replay_harness.py
git commit -m "feat: add mente replay harness core"
```

## Task 8: Add Replay Fixtures And End-To-End Replay Tests

**Files:**
- Create: `tests/mente/fixtures/replay/gateway_conversation.json`
- Create: `tests/mente/fixtures/replay/cron_job.json`
- Test: `tests/mente/test_replay_harness.py`

**Step 1: Write the failing test**

```python
from pathlib import Path

from mente.context_builder.builder import ContextBuilder
from mente.executors.base import Executor
from mente.memory.repository import InMemoryMemoryRepository
from mente.orchestrator.service import Orchestrator
from mente.task_core.models import ExecutionResult
from mente.task_core.repository import InMemoryTaskRepository
from mente.testing.replay import load_replay_fixture, replay_task


class _FakeExecutor(Executor):
    def execute(self, request):
        return ExecutionResult(status="success", summary=request.objective)


def test_gateway_fixture_replays():
    fixture = load_replay_fixture(Path("tests/mente/fixtures/replay/gateway_conversation.json"))
    result = replay_task(
        fixture,
        Orchestrator(
            repository=InMemoryTaskRepository(),
            context_builder=ContextBuilder(memory_repository=InMemoryMemoryRepository()),
            executor=_FakeExecutor(),
        ),
    )
    assert result.status == "success"
```

**Step 2: Run test to verify it fails**

Run: `uv run --extra dev pytest tests/mente/test_replay_harness.py -v`
Expected: missing fixture files or loader support

**Step 3: Write minimal implementation**

Add two tiny fixtures:

- `gateway_conversation.json`
- `cron_job.json`

Each fixture should contain:

- normalized `task`
- optional `notes`
- optional `expected` block for later comparison

Example:

```json
{
  "task": {
    "task_id": "fixture_gateway_task_1",
    "session_id": "fixture_gateway_session_1",
    "task_type": "conversation",
    "objective": "Continue the active conversation and answer the latest user message.",
    "user_request": "Summarize yesterday's discussion in two bullets.",
    "metadata": {
      "source": "gateway",
      "platform": "telegram"
    }
  },
  "notes": "Minimal gateway replay fixture"
}
```

**Step 4: Run test to verify it passes**

Run: `uv run --extra dev pytest tests/mente/test_replay_harness.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add tests/mente/fixtures/replay tests/mente/test_replay_harness.py
git commit -m "test: add mente replay fixtures"
```

## Task 9: Add A Narrow Replay CLI Entry Point

**Files:**
- Create: `mente/testing/cli.py`
- Test: `tests/mente/test_replay_cli.py`

**Step 1: Write the failing test**

```python
from mente.testing.cli import build_replay_parser


def test_replay_cli_accepts_fixture_path():
    parser = build_replay_parser()
    args = parser.parse_args(["tests/mente/fixtures/replay/gateway_conversation.json"])
    assert args.fixture_path.endswith("gateway_conversation.json")
```

**Step 2: Run test to verify it fails**

Run: `uv run --extra dev pytest tests/mente/test_replay_cli.py -v`
Expected: import failure for `mente.testing.cli`

**Step 3: Write minimal implementation**

Create a small CLI helper with:

- `build_replay_parser()`
- `main(argv=None)`

Flags:

- positional `fixture_path`
- optional `--executor mock|codex`
- optional `--workspace PATH`

For the initial slice, `mock` is enough for tests. `codex` can stay as a best-effort runtime mode and does not need test coverage beyond parser behavior.

**Step 4: Run test to verify it passes**

Run: `uv run --extra dev pytest tests/mente/test_replay_cli.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add mente/testing/cli.py tests/mente/test_replay_cli.py
git commit -m "feat: add mente replay cli"
```

## Task 10: Run The Phase 3 Verification Suite

**Files:**
- No code changes required unless tests fail

**Step 1: Run targeted Mente tests**

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

Expected: all PASS

**Step 2: Run adjacent regression tests**

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
  mente/testing \
  mente/context_builder/builder.py \
  mente/orchestrator/service.py \
  mente/integrations/hermes.py
```

Expected: exit code `0`

**Step 4: Commit final integration**

```bash
git add mente tests docs
git commit -m "feat: add mente phase 3 memory and replay runtime"
```

## Acceptance Criteria

Phase 3 is complete when all of the following are true:

- `Mente` owns a persistent memory store independent of `CodexExecutor`
- `ContextBuilder` deterministically injects retrieved memory into `ExecutionRequest.memory_facts`
- `Orchestrator` promotes `ExecutionResult.memory_candidates` into persistent memory
- promotion failures do not fail successful tasks
- replay can run a normalized `Task` fixture through the same orchestration path
- at least one gateway fixture and one cron fixture replay successfully with a mock executor
- prompt-facing memory strings stay stable enough to preserve cacheability

## Explicit Non-Goals

- no semantic embedding search
- no vector database
- no automatic memory summarization by Codex
- no dynamic memory ranking model
- no replay of raw Codex transcripts yet
- no visual replay dashboard yet

## Follow-On Work After Phase 3

1. Add memory inspection to `/api/debug/tasks` or a sibling `/api/debug/memories` endpoint.
2. Add replay result snapshots so expected `ExecutionResult` subsets can be asserted in fixtures.
3. Add scoped forgetting and retention policies.
4. Add a verifier stage that can promote only post-verification memories for higher trust.
