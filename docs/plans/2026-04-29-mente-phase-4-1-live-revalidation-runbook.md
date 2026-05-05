# Phase A Live Revalidation Runbook

**Purpose:** Validate the Phase A execution-isolation baseline end to end for the API server Mente path. A fresh session must not invent prior preferences, and a seeded session must still promote and inject real memory correctly.

**Environment:**

- `HERMES_HOME=/home/jason/.hermes-mente-smoke`
- API server: `http://127.0.0.1:8742`
- Dashboard: `http://127.0.0.1:9219`
- API key: `dev-key`

## Preconditions

- Stop earlier gateway, API server, and dashboard processes so ports and locks are clean.
- Keep the isolated `HERMES_HOME` dedicated to this validation run.
- Ensure both `HERMES_GATEWAY_EXECUTOR=mente` and `HERMES_API_SERVER_EXECUTOR=mente` are set before startup.
- Use brand-new session IDs for each smoke so prior task/memory rows cannot contaminate the result.

## Step 1: Start Gateway + API Server

```bash
cd /root/code/Mente

export HERMES_HOME=/home/jason/.hermes-mente-smoke
export HERMES_GATEWAY_EXECUTOR=mente
export HERMES_API_SERVER_EXECUTOR=mente

uv run python -m gateway.run
```

Expected:

- process stays in foreground
- API server binds `127.0.0.1:8742`
- no port-conflict or token-lock errors

## Step 2: Start Dashboard

Open a second terminal:

```bash
cd /root/code/Mente

export HERMES_HOME=/home/jason/.hermes-mente-smoke

uv run python -m hermes_cli.main dashboard --no-open --port 9219
```

Optional browser URL:

```text
http://127.0.0.1:9219
```

The dashboard is optional for this smoke, but useful for inspecting the isolated profile state.

## Step 3: Verify Health

Open a third terminal:

```bash
curl -sS http://127.0.0.1:8742/health
```

Expected:

```json
{"status": "ok", "platform": "hermes-agent"}
```

## Live Check A: Fresh Session Purity

Session ID: `mente-live-smoke-isolation-a`

### A1. First Turn

```bash
curl -sS http://127.0.0.1:8742/v1/chat/completions \
  -H 'Authorization: Bearer dev-key' \
  -H 'Content-Type: application/json' \
  -H 'X-Hermes-Session-Id: mente-live-smoke-isolation-a' \
  -d '{
    "model": "hermes-agent",
    "messages": [
      {"role": "user", "content": "What preferences did I mention earlier?"}
    ]
  }'
```

Pass criteria:

- HTTP succeeds
- assistant does **not** claim any specific earlier preference
- assistant explicitly reflects uncertainty or says no prior preference was provided

### A2. Inspect Task Trace

```bash
curl -sS 'http://127.0.0.1:8742/api/debug/tasks?scope=session&session_id=mente-live-smoke-isolation-a&source=api_server&task_type=conversation&limit=10' \
  -H 'Authorization: Bearer dev-key'
```

Pass criteria:

- `count >= 1`
- latest task has `source = "api_server"`
- latest task has `task_type = "conversation"`
- latest task has `metadata.memory_context.selected == []`
- latest task has `metadata.memory_promotion.promoted_count == 0`

### A3. Inspect Memory Trace

```bash
curl -sS 'http://127.0.0.1:8742/api/debug/memories?scope=session&session_id=mente-live-smoke-isolation-a&source=api_server&task_type=conversation&memory_scope=session&limit=10' \
  -H 'Authorization: Bearer dev-key'
```

Pass criteria:

- `count == 0`
- no session memory is created from the fresh-session purity probe

## Live Check B: Real Memory Promotion And Injection

Session ID: `mente-live-smoke-isolation-b`

### B1. First Turn

```bash
curl -sS http://127.0.0.1:8742/v1/chat/completions \
  -H 'Authorization: Bearer dev-key' \
  -H 'Content-Type: application/json' \
  -H 'X-Hermes-Session-Id: mente-live-smoke-isolation-b' \
  -d '{
    "model": "hermes-agent",
    "messages": [
      {"role": "user", "content": "Remember that I prefer short weekly summaries and JSON-first examples."}
    ]
  }'
```

Pass criteria:

- HTTP succeeds
- assistant acknowledges the stated preferences

### B2. Second Turn

```bash
curl -sS http://127.0.0.1:8742/v1/chat/completions \
  -H 'Authorization: Bearer dev-key' \
  -H 'Content-Type: application/json' \
  -H 'X-Hermes-Session-Id: mente-live-smoke-isolation-b' \
  -d '{
    "model": "hermes-agent",
    "messages": [
      {"role": "user", "content": "What preference did I mention earlier?"}
    ]
  }'
```

Pass criteria:

- HTTP succeeds
- assistant answers with one or more of the real stored preferences

### B3. Inspect Task Trace

```bash
curl -sS 'http://127.0.0.1:8742/api/debug/tasks?scope=session&session_id=mente-live-smoke-isolation-b&source=api_server&task_type=conversation&limit=10' \
  -H 'Authorization: Bearer dev-key'
```

Pass criteria:

- `count >= 2`
- first turn has `metadata.memory_promotion.promoted_count >= 1`
- second turn has non-empty `metadata.memory_context.selected`
- second turn has `metadata.memory_policy.policy_id` populated

### B4. Inspect Memory Trace

```bash
curl -sS 'http://127.0.0.1:8742/api/debug/memories?scope=session&session_id=mente-live-smoke-isolation-b&source=api_server&task_type=conversation&memory_scope=session&limit=10' \
  -H 'Authorization: Bearer dev-key'
```

Pass criteria:

- `count >= 1`
- returned memory rows have `source = "api_server"`
- returned memory rows have `scope = "session"`
- at least one `fact` reflects the weekly-summary or JSON-first preference

## Optional Raw DB Confirmation

If the debug API output looks suspicious, inspect the isolated SQLite state directly:

```bash
sqlite3 /home/jason/.hermes-mente-smoke/state.db "select task_id, session_id, source, task_type, status from mente_tasks order by updated_at desc limit 20;"
```

```bash
sqlite3 /home/jason/.hermes-mente-smoke/state.db "select memory_id, session_id, source, task_type, scope, fact from mente_memories order by created_at desc limit 20;"
```

## Acceptance Decision

Phase A live revalidation passes only if all of the following are true:

1. Live Check A first turn does not fabricate any prior preference recall.
2. Live Check A task trace shows `selected == []`.
3. Live Check A memory trace shows zero promoted session memories.
4. Live Check B first turn promotes at least one real memory.
5. Live Check B second turn injects previously promoted memory.
6. Both checks remain isolated from each other by session ID.

## Known Non-Goal

- This runbook establishes the pure execution baseline only.
- Do not treat it as approval for full fork work, `kernel/` migration, or packaging changes.
