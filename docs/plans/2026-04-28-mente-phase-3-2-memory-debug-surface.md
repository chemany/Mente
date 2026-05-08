# Phase 3.2: Memory Debug Surface Implementation Plan

> **For Mente:** Use `executing-plans` to implement this plan task-by-task.

**Goal:** Expose persisted Mente memories through a shared debug query surface and a dedicated dashboard page so engineers can inspect what memory was promoted, stored, and later retrieved.

**Architecture:** Keep the live memory loop unchanged. Add a debug-only listing surface on top of `MemoryRepository`, then mirror the existing `/api/debug/tasks` pattern: shared query helper, gateway route, dashboard route, and a same-origin `/memories` page in the web UI. Determinism matters here too: filtering, ordering, pagination, and serialized payloads must stay stable so the debug surface is useful for replay and cache-shape inspection.

**Tech Stack:** Python 3.11+, SQLite, pytest, aiohttp, FastAPI, React 19, TypeScript, existing Mente/Hermes dashboard build

---

## Scope

This slice is intentionally narrow:

- add repository listing methods for debug browsing
- add shared memory query parsing/execution helpers
- expose `GET /api/debug/memories` on gateway and dashboard backends
- add a dedicated `/memories` dashboard page with URL-synced filters, pagination, and detail expansion

Explicitly out of scope:

- semantic search
- retention / forgetting
- ranking changes for `ContextBuilder.list_relevant(...)`
- memory editing or deletion APIs
- cross-session aggregation beyond simple recent/session filters

## Query Shape

Match the existing tasks debug API as closely as possible.

Request filters:

- `scope=recent|session`
- `session_id=<id>` when `scope=session`
- `source=gateway|cron`
- `task_type=<name>`
- `memory_scope=session|task_type|global`
- `limit=<1..50>`
- `offset=<n>` or `cursor=<n>`

Response shape:

```json
{
  "query": {
    "scope": "recent",
    "session_id": null,
    "source": "gateway",
    "task_type": "conversation",
    "memory_scope": "session",
    "limit": 20,
    "offset": 0
  },
  "count": 1,
  "pagination": {
    "limit": 20,
    "offset": 0,
    "returned": 1,
    "has_more": false,
    "next_offset": null,
    "next_cursor": null
  },
  "memories": [
    {
      "memory_id": "mem_1",
      "session_id": "sess_1",
      "task_id": "task_1",
      "task_type": "conversation",
      "source": "gateway",
      "scope": "session",
      "fact": "User prefers concise replies.",
      "kind": "fact",
      "score": 1.0,
      "created_at": 1714300000.0,
      "metadata": {
        "promotion_reason": "executor_memory_candidate"
      }
    }
  ]
}
```

Sort order for debug listing should be recency-first, not relevance-first:

1. `created_at DESC`
2. `memory_id DESC`

## Task 1: Extend MemoryRepository With Debug Listing Methods

**Files:**
- Modify: `mente/memory/repository.py`
- Modify: `tests/mente/test_memory_repository.py`

**Step 1: Write the failing test**

Add repository coverage for both in-memory and SQLite debug listing methods.

```python
from mente.memory.models import MemoryRecord
from mente.memory.repository import SQLiteMemoryRepository


def test_sqlite_memory_repository_list_recent_filters_and_offset(tmp_path, monkeypatch):
    db_path = tmp_path / "memory.db"
    repo = SQLiteMemoryRepository(db_path=db_path)
    timestamps = iter([1000.0, 1001.0, 1002.0])
    monkeypatch.setattr("mente.memory.repository.time.time", lambda: next(timestamps))

    repo.save(MemoryRecord(
        memory_id="mem_1",
        session_id="sess-a",
        task_id="task_1",
        task_type="conversation",
        source="gateway",
        scope="session",
        fact="Older gateway fact",
    ))
    repo.save(MemoryRecord(
        memory_id="mem_2",
        session_id="sess-a",
        task_id="task_2",
        task_type="conversation",
        source="gateway",
        scope="session",
        fact="Newer gateway fact",
    ))
    repo.save(MemoryRecord(
        memory_id="mem_3",
        session_id="sess-b",
        task_id="task_3",
        task_type="cron",
        source="cron",
        scope="task_type",
        fact="Cron fact",
    ))

    rows = repo.list_recent(limit=1, offset=1, source="gateway")
    assert [row.memory_id for row in rows] == ["mem_1"]


def test_sqlite_memory_repository_list_by_session_filters_scope_and_task_type(tmp_path):
    db_path = tmp_path / "memory.db"
    repo = SQLiteMemoryRepository(db_path=db_path)
    repo.save(MemoryRecord(
        memory_id="mem_session",
        session_id="sess-1",
        task_id="task_1",
        task_type="conversation",
        source="gateway",
        scope="session",
        fact="Session fact",
    ))
    repo.save(MemoryRecord(
        memory_id="mem_task_type",
        session_id="sess-1",
        task_id="task_2",
        task_type="cron",
        source="cron",
        scope="task_type",
        fact="Wrong type",
    ))

    rows = repo.list_by_session(
        "sess-1",
        task_type="conversation",
        memory_scope="session",
    )
    assert [row.memory_id for row in rows] == ["mem_session"]
```

**Step 2: Run test to verify it fails**

Run: `uv run --extra dev pytest tests/mente/test_memory_repository.py -v`
Expected: failure because `MemoryRepository` implementations do not yet expose `list_recent(...)` / `list_by_session(...)`

**Step 3: Write minimal implementation**

Extend `mente/memory/repository.py`:

- add protocol methods:
  - `list_recent(limit=20, offset=0, source=None, task_type=None, memory_scope=None)`
  - `list_by_session(session_id, limit=20, offset=0, source=None, task_type=None, memory_scope=None)`
- implement both methods for `InMemoryMemoryRepository`
- implement both methods for `SQLiteMemoryRepository`
- keep `list_relevant(...)` unchanged for the live retrieval path

Rules:

- `list_recent(...)` returns newest-first across all memories
- `list_by_session(...)` only returns rows with matching `session_id`
- optional filters apply conjunctively
- `memory_scope` filters the stored record `scope` field
- pagination uses `LIMIT` + `OFFSET`

**Step 4: Run test to verify it passes**

Run: `uv run --extra dev pytest tests/mente/test_memory_repository.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add mente/memory/repository.py tests/mente/test_memory_repository.py
git commit -m "feat: add memory debug listing repository methods"
```

## Task 2: Add Shared Memory Query Helpers And Backend Debug APIs

**Files:**
- Create: `mente/memory/memory_query.py`
- Modify: `gateway/platforms/api_server.py`
- Modify: `hermes_cli/web_server.py`
- Create: `tests/mente/test_memory_query.py`
- Create: `tests/gateway/test_api_server_memories.py`
- Modify: `tests/hermes_cli/test_web_server.py`

**Step 1: Write the failing tests**

Add one parser/executor test plus one gateway route test and one dashboard route test.

```python
from mente.memory.memory_query import parse_http_memory_query


def test_parse_http_memory_query_normalizes_filters():
    query = parse_http_memory_query(
        {
            "scope": "session",
            "session_id": "sess-42",
            "source": "gateway",
            "task_type": "conversation",
            "memory_scope": "session",
            "cursor": "10",
            "limit": "50",
        }
    )
    assert query == {
        "scope": "session",
        "session_id": "sess-42",
        "source": "gateway",
        "task_type": "conversation",
        "memory_scope": "session",
        "limit": 50,
        "offset": 10,
    }
```

Gateway/API shape should mirror tasks:

```python
assert data["pagination"] == {
    "limit": 1,
    "offset": 0,
    "returned": 1,
    "has_more": False,
    "next_offset": None,
    "next_cursor": None,
}
assert data["memories"][0]["memory_id"] == "mem_001"
assert data["memories"][0]["fact"] == "User prefers concise replies."
```

**Step 2: Run tests to verify they fail**

Run: `uv run --extra dev pytest tests/mente/test_memory_query.py tests/gateway/test_api_server_memories.py tests/hermes_cli/test_web_server.py -k "memory_query or debug_memories" -v`
Expected: import failure for `mente.memory.memory_query` and missing `/api/debug/memories` routes

**Step 3: Write minimal implementation**

Create `mente/memory/memory_query.py` with:

- `MemoryQueryError`
- `parse_http_memory_query(params)`
- `execute_memory_query(query, repository_factory)`
- `serialize_memory_query(query)`
- `serialize_memory(record)`

Implement the same pagination contract as tasks:

- fetch `limit + 1`
- compute `has_more`
- return `next_offset` and `next_cursor`

Backend wiring:

- add `GET /api/debug/memories` to `gateway/platforms/api_server.py`
- add `GET /api/debug/memories` to `hermes_cli/web_server.py`
- use `SQLiteMemoryRepository` as the repository factory
- keep dashboard auth behavior identical to `/api/debug/tasks`
- keep gateway API-key auth behavior identical to `/api/debug/tasks`

**Step 4: Run tests to verify they pass**

Run: `uv run --extra dev pytest tests/mente/test_memory_query.py tests/gateway/test_api_server_memories.py tests/hermes_cli/test_web_server.py -k "memory_query or debug_memories" -v`
Expected: PASS

**Step 5: Commit**

```bash
git add mente/memory/memory_query.py gateway/platforms/api_server.py hermes_cli/web_server.py tests/mente/test_memory_query.py tests/gateway/test_api_server_memories.py tests/hermes_cli/test_web_server.py
git commit -m "feat: add memory debug api surface"
```

## Task 3: Add Dashboard API Types And URL-State Helpers

**Files:**
- Modify: `web/src/lib/api.ts`
- Create: `web/src/pages/memories-url-state.ts`
- Create: `web/tests/memories-url-state.test.ts`

**Step 1: Write the failing test**

Mirror the existing task URL-state test style.

```ts
import assert from "node:assert/strict";
import {
  buildMemoryQueryParams,
  parseMemoryQueryState,
} from "../src/pages/memories-url-state.ts";

{
  const parsed = parseMemoryQueryState(
    new URLSearchParams(
      "scope=session&session_id=sess-42&source=gateway&task_type=conversation&memory_scope=session&cursor=10&limit=50&memory_id=mem-9",
    ),
  );

  assert.deepEqual(parsed.filters, {
    scope: "session",
    sessionId: "sess-42",
    source: "gateway",
    taskType: "conversation",
    memoryScope: "session",
    limit: 50,
  });
  assert.equal(parsed.offset, 10);
  assert.equal(parsed.memoryId, "mem-9");
}
```

**Step 2: Run test to verify it fails**

Run: `node web/tests/memories-url-state.test.ts`
Expected: module-not-found failure for `web/src/pages/memories-url-state.ts`

**Step 3: Write minimal implementation**

Update `web/src/lib/api.ts`:

- add `api.getDebugMemories(...)`
- add `DebugMemory`
- add `DebugMemoriesQuery`
- add `DebugMemoriesResponse`
- add `DebugMemoriesParams`

Create `web/src/pages/memories-url-state.ts` with:

- `MemoryFilters`
- `MemoryQueryState`
- `DEFAULT_MEMORY_FILTERS`
- `parseMemoryQueryState(...)`
- `buildMemoryQueryParams(...)`
- `memoryFiltersEqual(...)`

Use the same conventions as tasks:

- `cursor` aliases `offset`
- omit default values from the URL
- include `memory_id` for deep-link expansion

**Step 4: Run test to verify it passes**

Run: `node web/tests/memories-url-state.test.ts`
Expected: PASS with `memories-url-state tests passed`

**Step 5: Commit**

```bash
git add web/src/lib/api.ts web/src/pages/memories-url-state.ts web/tests/memories-url-state.test.ts
git commit -m "feat: add memory debug client query state"
```

## Task 4: Add The `/memories` Dashboard Page

**Files:**
- Create: `web/src/pages/MemoriesPage.tsx`
- Modify: `web/src/App.tsx`
- Modify: `web/src/lib/resolve-page-title.ts`
- Modify: `web/src/i18n/types.ts`
- Modify: `web/src/i18n/en.ts`
- Modify: `web/src/i18n/zh.ts`
- Modify: `web/src/plugins/slots.ts`

**Step 1: Introduce the failing integration point**

Wire the route and navigation before the page exists:

- import `MemoriesPage` in `web/src/App.tsx`
- add `"/memories": MemoriesPage` to built-in routes
- add a nav item beside `"/tasks"`

Then run the frontend build.

**Step 2: Run build to verify it fails**

Run: `npm --prefix web run build`
Expected: TypeScript import failure because `web/src/pages/MemoriesPage.tsx` and related strings/types do not exist yet

**Step 3: Write minimal implementation**

Build `web/src/pages/MemoriesPage.tsx` by following `TasksPage.tsx` closely:

- same URL-sync flow
- same pagination footer behavior
- same expandable row pattern
- same page-header badges

But render memory-specific fields:

- row summary: `fact`
- badges: `source`, `task_type`, `scope`, optionally `kind`
- detail meta: `memory_id`, `task_id`, `session_id`, `score`, `created_at`
- raw payload panel: full serialized memory JSON

Also:

- add i18n keys under a new `memories` section
- add title resolution for `"/memories"`
- add plugin slots:
  - `memories:top`
  - `memories:bottom`

Do not add edit/delete controls in this phase.

**Step 4: Run verification**

Run: `npm --prefix web run build`
Expected: PASS

Run: `npm --prefix web run lint`
Expected: PASS

Optional smoke check after build:

```bash
python -m hermes_cli.main web --port 9119
# open http://127.0.0.1:9119/memories
```

Confirm:

- filters sync to URL
- `memory_id` deep-link expands the selected row
- next/previous pagination preserves filters
- raw payload panel shows `metadata`

**Step 5: Commit**

```bash
git add web/src/pages/MemoriesPage.tsx web/src/App.tsx web/src/lib/resolve-page-title.ts web/src/i18n/types.ts web/src/i18n/en.ts web/src/i18n/zh.ts web/src/plugins/slots.ts
git commit -m "feat: add dashboard memory debug page"
```

## Final Verification

Run:

```bash
uv run --extra dev pytest tests/mente/test_memory_repository.py tests/mente/test_memory_query.py tests/gateway/test_api_server_memories.py tests/hermes_cli/test_web_server.py -k "memory or debug_memories" -v
node web/tests/memories-url-state.test.ts
npm --prefix web run build
npm --prefix web run lint
```

Expected:

- Python debug-memory tests pass
- URL-state test prints `memories-url-state tests passed`
- dashboard build succeeds
- dashboard lint succeeds
