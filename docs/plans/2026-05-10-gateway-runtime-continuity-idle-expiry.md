# Gateway Runtime Continuity Idle Expiry Implementation Plan

> **For Mente:** REQUIRED SKILL: Use `executing-plans` to implement this plan task-by-task.

**Goal:** Expire idle Mente gateway runtime continuity after a bounded inactivity window so long-idle chats start a fresh continuity session while preserving session records and transcripts.

**Architecture:** Keep the existing session/transcript model intact and add a continuity-level idle TTL on top of it. The gateway should inspect persisted continuity metadata before deciding to resume; stale bindings are invalidated and the next turn starts a fresh continuity session with one-time fallback history replay.

**Tech Stack:** Python, gateway session store, gateway runner continuity planner, pytest via `scripts/run_tests.sh`

---

### Task 1: Add failing continuity-idle tests

**Files:**
- Modify: `tests/gateway/test_gateway_runtime_continuity.py`
- Modify: `tests/gateway/test_session.py`

**Step 1: Write the failing test**

Add tests that cover:
- an active continuity payload older than the idle TTL is treated as stale and results in `ExecutionSession(mode=SessionMode.START)`
- stale continuity is marked invalidated with a specific reason
- fresh continuity still resumes
- session-store continuity invalidation preserves metadata and updates timestamps

**Step 2: Run test to verify it fails**

Run: `scripts/run_tests.sh tests/gateway/test_gateway_runtime_continuity.py tests/gateway/test_session.py -k 'continuity_idle or stale_continuity'`

Expected: FAIL because the gateway currently resumes any active codex continuity regardless of age.

**Step 3: Commit**

Do not commit yet; continue after implementation passes.

### Task 2: Implement idle TTL and invalidation path

**Files:**
- Modify: `gateway/run.py`
- Modify: `gateway/session.py`
- Modify: `mente/feature_flags.py`

**Step 1: Write minimal implementation**

Add:
- a small helper that resolves gateway runtime continuity idle TTL seconds from env
- a helper that determines whether a persisted continuity payload is stale from `updated_at`
- a gateway preflight that invalidates stale continuity before planning `resume` vs `start`
- optional session-store helper for one-shot stale invalidation if that keeps `gateway/run.py` cleaner

Use a narrow invalidation reason such as `idle_ttl_expired`.

**Step 2: Make plan resolution fail closed**

When continuity is stale:
- do not resume it
- invalidate it for diagnostics
- build `ExecutionSession(mode=SessionMode.START)`
- keep one-time fallback history replay enabled exactly as current start-path does

**Step 3: Run focused tests**

Run: `scripts/run_tests.sh tests/gateway/test_gateway_runtime_continuity.py tests/gateway/test_session.py -k 'continuity_idle or stale_continuity'`

Expected: PASS

### Task 3: Wire session-expiry cleanup to retire old continuity bindings

**Files:**
- Modify: `gateway/run.py`
- Test: `tests/gateway/test_gateway_runtime_continuity.py`

**Step 1: Add a regression test**

Cover that the background session-expiry cleanup invalidates any active codex continuity bound to the expired session with a stable reason.

**Step 2: Implement minimal cleanup**

In the session-expiry watcher, after finalizing an expired session, invalidate any active codex continuity bound to that `session_id`.

**Step 3: Run target tests**

Run: `scripts/run_tests.sh tests/gateway/test_gateway_runtime_continuity.py tests/gateway/test_session_store_prune.py`

Expected: PASS

### Task 4: Run gateway bridge regressions

**Files:**
- Verify only

**Step 1: Run the relevant regression suites**

Run: `scripts/run_tests.sh tests/gateway/test_gateway_runtime_continuity.py tests/gateway/test_mente_task_bridge.py tests/gateway/test_session.py`

Expected: PASS

**Step 2: Summarize operational semantics**

Document in the final response:
- continuity is now auto-retired after idle TTL
- transcripts/session records remain
- the next inbound task automatically starts a fresh continuity session
- there is no long-lived local Codex subprocess to kill between turns; the durable object was the continuity binding
