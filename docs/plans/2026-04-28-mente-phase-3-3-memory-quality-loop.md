# Phase 3.3: Memory Quality Loop Implementation Plan

> **For Mente:** Use `executing-plans` to implement this plan task-by-task.

**Goal:** Make Mente memory observable and replay-evaluable by recording why memories were injected, what was promoted, and how a replay run differs with memory enabled versus disabled.

**Architecture:** Phase 3.3 does not change the live memory ranking rules or add new storage primitives. Instead, it adds a sidecar diagnostics path around the existing `ContextBuilder` and `Orchestrator`, then extends the replay harness so the same normalized task can be compared in baseline and memory-enabled modes. Prompt-facing `memory_facts` must remain byte-stable; all new explanation and metrics data lives in metadata or replay reports, not in the executor prompt.

**Tech Stack:** Python 3.11+, Pydantic 2, pytest, existing `mente` runtime, replay harness, SQLite-backed Mente persistence

---

## Scope

This slice is intentionally narrow:

- record deterministic memory retrieval and injection traces
- persist memory retrieval/promotion summaries into task/result metadata
- add replay comparison mode for memory-off vs memory-on evaluation
- expose explanation fields through existing serialized task metadata without requiring new APIs

Explicitly out of scope:

- semantic search
- retention / forgetting
- automatic score tuning
- LLM-based memory classification
- editable memory UI actions
- changing the prompt text format of injected memories

## Design Constraints

- Do not modify `CodexExecutor` behavior for memory ownership.
- Do not change the existing retrieval order from `list_relevant(...)`.
- Do not include timestamps, scores, ids, or diagnostic prose in prompt-facing `request.memory_facts`.
- Keep explanation payloads deterministic and JSON-serializable.
- Ensure tasks without memory records still behave exactly as before.

## Proposed Trace Shape

Persist a compact sidecar trace, not a transcript:

```python
{
  "memory_context": {
    "retrieved_count": 2,
    "injected_count": 1,
    "selected": [
      {
        "memory_id": "mem_1",
        "scope": "session",
        "fact": "User prefers concise replies.",
        "reason": "scope_match",
      }
    ],
    "skipped": [
      {
        "memory_id": "mem_2",
        "reason": "duplicate_existing_fact",
      }
    ],
  },
  "memory_promotion": {
    "candidate_count": 2,
    "promoted_count": 1,
    "promoted_memory_ids": ["task_1:memory:0"],
  },
}
```

`reason` values must be fixed enums, not free text:

- `scope_match`
- `duplicate_existing_fact`
- `duplicate_injected_fact`
- `memory_limit_reached`

## Task 1: Add Deterministic Memory Trace Models And ContextBuilder Diagnostics

**Files:**
- Modify: `mente/memory/models.py`
- Modify: `mente/context_builder/builder.py`
- Modify: `tests/mente/test_context_builder.py`
- Modify: `tests/mente/test_memory_models.py`

**Step 1: Write the failing tests**

Add model coverage for the new trace payloads and a `ContextBuilder` regression proving diagnostics are captured without changing prompt-facing `memory_facts`.

```python
from mente.context_builder.builder import ContextBuilder
from mente.memory.models import MemoryRecord
from mente.memory.repository import InMemoryMemoryRepository
from mente.task_core.models import Task


def test_context_builder_build_with_trace_reports_selected_and_skipped():
    memory_repo = InMemoryMemoryRepository()
    memory_repo.save(MemoryRecord(
        memory_id="mem_1",
        session_id="session_1",
        task_id="task_old_1",
        task_type="conversation",
        source="gateway",
        scope="session",
        fact="User prefers concise replies.",
    ))
    memory_repo.save(MemoryRecord(
        memory_id="mem_2",
        session_id="session_1",
        task_id="task_old_2",
        task_type="conversation",
        source="gateway",
        scope="session",
        fact="Session context: existing",
    ))

    task = Task(
        task_id="task_1",
        session_id="session_1",
        task_type="conversation",
        objective="Reply",
        user_request="Reply",
        memory_facts=["Session context: existing"],
    )

    request, trace = ContextBuilder(
        memory_repository=memory_repo,
        memory_limit=5,
    ).build_with_trace(task)

    assert request.memory_facts == [
        "Memory: User prefers concise replies.",
        "Session context: existing",
    ]
    assert trace.injected_count == 1
    assert [item.memory_id for item in trace.selected] == ["mem_1"]
    assert [(item.memory_id, item.reason) for item in trace.skipped] == [
        ("mem_2", "duplicate_existing_fact"),
    ]
```

**Step 2: Run tests to verify they fail**

Run: `uv run --extra dev pytest tests/mente/test_memory_models.py tests/mente/test_context_builder.py -v`
Expected: failure because trace models and `build_with_trace(...)` do not exist yet

**Step 3: Write minimal implementation**

Extend `mente/memory/models.py` with compact diagnostics models:

- `MemoryTraceItem`
- `MemoryBuildTrace`

Recommended shape:

```python
class MemoryTraceItem(BaseModel):
    memory_id: str
    scope: str
    fact: str
    reason: str


class MemoryBuildTrace(BaseModel):
    retrieved_count: int = 0
    injected_count: int = 0
    selected: list[MemoryTraceItem] = Field(default_factory=list)
    skipped: list[MemoryTraceItem] = Field(default_factory=list)
```

Update `ContextBuilder`:

- keep `build(task)` as the compatibility path
- add `build_with_trace(task) -> tuple[ExecutionRequest, MemoryBuildTrace]`
- make `build(task)` call the trace-aware path and return only the request
- populate deterministic skip reasons
- keep `request.memory_facts` output exactly unchanged from current behavior

**Step 4: Run tests to verify they pass**

Run: `uv run --extra dev pytest tests/mente/test_memory_models.py tests/mente/test_context_builder.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add mente/memory/models.py mente/context_builder/builder.py tests/mente/test_memory_models.py tests/mente/test_context_builder.py
git commit -m "feat: add deterministic memory build traces"
```

## Task 2: Persist Memory Observability Into Orchestrator Metadata

**Files:**
- Modify: `mente/orchestrator/service.py`
- Modify: `tests/mente/test_orchestrator_service.py`
- Modify: `tests/mente/test_hermes_integration.py`

**Step 1: Write the failing tests**

Add orchestration coverage proving retrieval and promotion summaries are persisted into task and result metadata.

```python
from mente.context_builder.builder import ContextBuilder
from mente.executors.base import Executor
from mente.memory.models import MemoryRecord
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


def test_orchestrator_persists_memory_context_and_promotion_metadata():
    task_repo = InMemoryTaskRepository()
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
    orchestrator = Orchestrator(
        repository=task_repo,
        context_builder=ContextBuilder(memory_repository=memory_repo),
        executor=_ExecutorWithMemory(),
        memory_repository=memory_repo,
        memory_promoter=MemoryPromoter(),
    )
    task = Task(
        task_id="task_1",
        session_id="session_1",
        task_type="conversation",
        objective="Reply",
        user_request="Reply",
        metadata={"source": "gateway"},
    )

    result = orchestrator.run(task)
    persisted = task_repo.get("task_1")

    assert result.metadata["memory_context"]["injected_count"] == 1
    assert result.metadata["memory_promotion"]["promoted_count"] == 1
    assert persisted is not None
    assert persisted.metadata["memory_context"]["selected"][0]["memory_id"] == "mem_1"
    assert persisted.metadata["memory_promotion"]["promoted_memory_ids"] == ["task_1:memory:0"]
```

**Step 2: Run tests to verify they fail**

Run: `uv run --extra dev pytest tests/mente/test_orchestrator_service.py tests/mente/test_hermes_integration.py -v`
Expected: failure because orchestrator does not yet persist `memory_context` / `memory_promotion`

**Step 3: Write minimal implementation**

Update `mente/orchestrator/service.py`:

- call `context_builder.build_with_trace(task)` instead of `build(task)`
- write `task.metadata["memory_context"] = trace.model_dump(mode="json")`
- also write the same serialized trace into `result.metadata["memory_context"]`
- extend `_persist_promoted_memory(...)` to write:
  - `candidate_count`
  - `promoted_count`
  - `promoted_memory_ids`
- persist the promotion summary into both `task.metadata["memory_promotion"]` and `result.metadata["memory_promotion"]`
- keep the existing `promoted_memory_count` field for backward compatibility

Do not fail task execution if diagnostics serialization or memory persistence has issues.

**Step 4: Run tests to verify they pass**

Run: `uv run --extra dev pytest tests/mente/test_orchestrator_service.py tests/mente/test_hermes_integration.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add mente/orchestrator/service.py tests/mente/test_orchestrator_service.py tests/mente/test_hermes_integration.py
git commit -m "feat: persist memory observability metadata"
```

## Task 3: Add Replay Comparison For Memory-Off Vs Memory-On

**Files:**
- Modify: `mente/testing/replay.py`
- Modify: `mente/testing/cli.py`
- Modify: `tests/mente/test_replay_harness.py`
- Modify: `tests/mente/test_replay_cli.py`
- Modify: `tests/mente/fixtures/replay/gateway_conversation.json`

**Step 1: Write the failing tests**

Add replay coverage proving the same normalized task can be evaluated in baseline and memory-enabled modes with a deterministic comparison report.

```python
from mente.context_builder.builder import ContextBuilder
from mente.executors.base import Executor
from mente.memory.repository import InMemoryMemoryRepository
from mente.orchestrator.service import Orchestrator
from mente.task_core.models import ExecutionResult
from mente.task_core.repository import InMemoryTaskRepository
from mente.testing.replay import compare_memory_replay


class _RecordingExecutor(Executor):
    def __init__(self):
        self.requests = []

    def execute(self, request):
        self.requests.append(request)
        return ExecutionResult(status="success", summary=request.objective)


def test_compare_memory_replay_reports_injected_memory():
    fixture = {
        "seed_memories": [
            {
                "memory_id": "mem_1",
                "session_id": "session_1",
                "task_id": "task_old",
                "task_type": "conversation",
                "source": "gateway",
                "scope": "session",
                "fact": "User prefers concise replies.",
            }
        ],
        "task": {
            "task_id": "task_1",
            "session_id": "session_1",
            "task_type": "conversation",
            "objective": "Reply",
            "user_request": "Reply",
        },
    }
    comparison = compare_memory_replay(
        fixture,
        executor_factory=_RecordingExecutor,
    )
    assert comparison["baseline"]["memory_fact_count"] == 0
    assert comparison["memory_enabled"]["memory_fact_count"] == 1
    assert comparison["memory_enabled"]["selected_memory_ids"] == ["mem_1"]
```

Also extend CLI coverage:

```python
from mente.testing.cli import build_replay_parser


def test_replay_cli_accepts_compare_memory_flag():
    parser = build_replay_parser()
    args = parser.parse_args([
        "tests/mente/fixtures/replay/gateway_conversation.json",
        "--compare-memory",
    ])
    assert args.compare_memory is True
```

**Step 2: Run tests to verify they fail**

Run: `uv run --extra dev pytest tests/mente/test_replay_harness.py tests/mente/test_replay_cli.py -v`
Expected: failure because comparison mode and CLI flag do not exist

**Step 3: Write minimal implementation**

Extend replay support:

- allow fixtures to optionally carry `seed_memories`
- add `compare_memory_replay(fixture, executor_factory, workspace=".")`
- return a JSON-safe report with:
  - `baseline.memory_fact_count`
  - `baseline.memory_facts`
  - `memory_enabled.memory_fact_count`
  - `memory_enabled.memory_facts`
  - `memory_enabled.selected_memory_ids`
  - `memory_enabled.promoted_memory_ids`
- reuse the same normalized task in both modes
- use isolated in-memory repositories so the two runs do not contaminate each other

Update CLI:

- add `--compare-memory`
- when enabled, print the comparison JSON instead of only `result.summary`
- keep existing default replay flow unchanged

**Step 4: Run tests to verify they pass**

Run: `uv run --extra dev pytest tests/mente/test_replay_harness.py tests/mente/test_replay_cli.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add mente/testing/replay.py mente/testing/cli.py tests/mente/test_replay_harness.py tests/mente/test_replay_cli.py tests/mente/fixtures/replay/gateway_conversation.json
git commit -m "feat: add memory replay comparison mode"
```

## Final Verification

Run:

```bash
uv run --extra dev pytest tests/mente/test_memory_models.py tests/mente/test_context_builder.py tests/mente/test_orchestrator_service.py tests/mente/test_hermes_integration.py tests/mente/test_replay_harness.py tests/mente/test_replay_cli.py -v
uv run --extra dev pytest tests/mente/test_memory_repository.py tests/mente/test_memory_promoter.py tests/mente/test_context_builder.py tests/mente/test_orchestrator_service.py tests/mente/test_hermes_integration.py tests/mente/test_replay_harness.py tests/mente/test_replay_cli.py -v
uv run python -m compileall mente/memory mente/context_builder mente/orchestrator mente/testing
```

Expected:

- all targeted Phase 3 memory tests pass
- replay comparison tests pass
- compileall exits `0`
