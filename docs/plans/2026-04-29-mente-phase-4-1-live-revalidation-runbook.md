# Phase 4.1 Live Revalidation Runbook

**Purpose:** Re-verify that the API server now routes non-streaming requests through Mente and that `source=api_server` task/memory records appear in the debug surfaces.

**Environment:**

- `HERMES_HOME=/home/jason/.hermes-mente-smoke`
- API server: `http://127.0.0.1:8742`
- Dashboard: `http://127.0.0.1:9219`
- API key: `dev-key`

## Preconditions

- Close the earlier gateway/API server and dashboard terminals so ports and locks are released.
- Keep the isolated `HERMES_HOME` created for Mente validation.
- Ensure `HERMES_API_SERVER_EXECUTOR=mente` is set before starting the gateway.

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
- no `Port 8642 already in use`
- no `Weixin bot token already in use`

## Step 2: Start Dashboard

Open a second terminal:

```bash
cd /root/code/Mente

export HERMES_HOME=/home/jason/.hermes-mente-smoke

uv run python -m hermes_cli.main dashboard --no-open --port 9219
```

Open:

```text
http://127.0.0.1:9219
```

Dashboard is optional for the API-only smoke, but useful for manual inspection.

## Step 3: Verify Health

Open a third terminal:

```bash
curl -sS http://127.0.0.1:8742/health
```

Expected:

```json
{"status": "ok", "platform": "hermes-agent"}
```

## Step 4: First Turn

```bash
curl -sS http://127.0.0.1:8742/v1/chat/completions \
  -H 'Authorization: Bearer dev-key' \
  -H 'Content-Type: application/json' \
  -H 'X-Hermes-Session-Id: mente-live-smoke-1' \
  -d '{
    "model": "hermes-agent",
    "messages": [
      {"role": "user", "content": "Remember that I prefer short weekly summaries."}
    ]
  }'
```

Expected at a minimum:

- HTTP succeeds
- assistant confirms the preference
- later `/api/debug/tasks` inspection must show this turn has `metadata.memory_promotion.promoted_count >= 1`

## Step 5: Second Turn

```bash
curl -sS http://127.0.0.1:8742/v1/chat/completions \
  -H 'Authorization: Bearer dev-key' \
  -H 'Content-Type: application/json' \
  -H 'X-Hermes-Session-Id: mente-live-smoke-1' \
  -d '{
    "model": "hermes-agent",
    "messages": [
      {"role": "user", "content": "What preference did I mention earlier?"}
    ]
  }'
```

Expected at a minimum:

- HTTP succeeds
- assistant answers with the earlier preference
- later `/api/debug/tasks` inspection must show this turn has non-empty `metadata.memory_context.selected`

## Step 6: Inspect Task Trace

```bash
curl -sS 'http://127.0.0.1:8742/api/debug/tasks?scope=session&session_id=mente-live-smoke-1&source=api_server&task_type=conversation&limit=10' \
  -H 'Authorization: Bearer dev-key'
```

Pass criteria:

- `count >= 2`
- latest tasks have `source = "api_server"`
- latest tasks have `task_type = "conversation"`
- the first turn shows `metadata.memory_promotion.promoted_count >= 1`
- the second turn shows non-empty `metadata.memory_context.selected`
- `metadata.memory_policy.policy_id` is populated

## Step 7: Inspect Memory Trace

```bash
curl -sS 'http://127.0.0.1:8742/api/debug/memories?scope=session&session_id=mente-live-smoke-1&source=api_server&task_type=conversation&limit=10' \
  -H 'Authorization: Bearer dev-key'
```

Pass criteria:

- `count >= 1`
- returned memory rows have `source = "api_server"`
- returned memory rows have `scope = "session"`
- at least one `fact` reflects the weekly-summary preference
- at least one returned row corresponds to the promoted first-turn fact

## Step 8: Optional Raw DB Confirmation

If the debug API output looks suspicious, confirm directly against the isolated SQLite state:

```bash
sqlite3 /home/jason/.hermes-mente-smoke/state.db "select task_id, session_id, source, task_type, status from mente_tasks order by updated_at desc limit 10;"
```

```bash
sqlite3 /home/jason/.hermes-mente-smoke/state.db "select memory_id, session_id, source, task_type, scope, fact from mente_memories order by created_at desc limit 10;"
```

## Acceptance Decision

Phase 4.1 live revalidation passes only if all of the following are true:

1. Both chat-completions calls succeed.
2. The second answer correctly references the earlier preference.
3. The first task has `metadata.memory_promotion.promoted_count >= 1`.
4. The second task has non-empty `metadata.memory_context.selected`.
5. `/api/debug/tasks` returns `source=api_server` tasks for the same session.
6. `/api/debug/memories` returns at least one `source=api_server` session memory that matches the promoted fact.

## Known Non-Goal

- Do not use the current `live-eval` fixture as the final judge here. It still reflects the older `gateway`-oriented assumptions and should be aligned in a later slice.
