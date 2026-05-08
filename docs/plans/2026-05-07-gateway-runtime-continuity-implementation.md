# Gateway Runtime Continuity Implementation Plan

> **For Mente:** Use `executing-plans` to implement this plan task-by-task.

**Goal:** Bind each gateway `session_id` to a reusable Codex runtime `continuity_id` (`thread_id`), use runtime resume as the primary path for follow-up user turns, and preserve transcript replay as a deterministic fallback when continuity is missing or invalid.

**Architecture:** Keep gateway session identity and runtime continuity as separate layers. `gateway/session.py` remains the source of truth for `session_key -> session_id`, while a new continuity store records `session_id -> continuity state`. Gateway turn dispatch resolves `start` vs `resume` before calling the Mente bridge, the bridge threads that continuity into `ExecutionRequest`, and `CodexExecutor` performs a resume-first call with a transcript-replay fallback request when runtime resume fails.

**Tech Stack:** Python, gateway session/transcript store, Mente task bridge, Codex executor/kernel runner, pytest via `scripts/run_tests.sh`

---

### Task 1: Add Gateway Runtime Continuity Persistence

**Files:**
- Modify: `gateway/session.py`
- Test: `tests/gateway/test_session.py`
- Optional new test file if `test_session.py` gets too crowded: `tests/gateway/test_runtime_continuity_store.py`

**Step 1: Write the failing continuity-store tests**

Add tests that pin the new store contract on `SessionStore`:

```python
def test_runtime_continuity_round_trip(tmp_path):
    store = SessionStore(sessions_dir=tmp_path, config=GatewayConfig())
    store.bind_runtime_continuity(
        session_id="sess-1",
        runtime="codex",
        continuity_id="thread-1",
        status="active",
        last_mode="start",
    )

    payload = store.get_runtime_continuity("sess-1")
    assert payload["continuity_id"] == "thread-1"
    assert payload["status"] == "active"
    assert payload["runtime"] == "codex"


def test_runtime_continuity_invalidation_marks_entry_but_keeps_record(tmp_path):
    store = SessionStore(sessions_dir=tmp_path, config=GatewayConfig())
    store.bind_runtime_continuity(
        session_id="sess-1",
        runtime="codex",
        continuity_id="thread-1",
        status="active",
    )

    store.invalidate_runtime_continuity("sess-1", reason="retry_rewrite")
    payload = store.get_runtime_continuity("sess-1")
    assert payload["status"] == "invalidated"
    assert payload["invalidation_reason"] == "retry_rewrite"
```

**Step 2: Run the targeted tests and confirm they fail**

Run:

```bash
scripts/run_tests.sh tests/gateway/test_session.py -v
```

Expected: failures for missing continuity methods and/or missing serialized state.

**Step 3: Implement the continuity store in `SessionStore`**

Add a second persisted index next to `sessions.json`, for example `runtime_continuity.json`, and wire these APIs:

```python
def get_runtime_continuity(self, session_id: str) -> dict[str, Any] | None: ...
def bind_runtime_continuity(
    self,
    session_id: str,
    *,
    runtime: str,
    continuity_id: str,
    status: str = "active",
    last_task_id: str | None = None,
    last_mode: str | None = None,
    last_fallback_reason: str | None = None,
) -> None: ...
def invalidate_runtime_continuity(self, session_id: str, *, reason: str) -> bool: ...
def clear_runtime_continuity(self, session_id: str) -> bool: ...
```

Implementation constraints:
- Keep continuity keyed by `session_id`, not `session_key`.
- Persist `created_at` and `updated_at`.
- Do not silently delete invalidated entries; preserve them for diagnostics.
- Load/save continuity state under the same lock discipline already used by `SessionStore`.

**Step 4: Extend reset/switch helpers to maintain correct continuity ownership**

Update `reset_session()` and `switch_session()` semantics:
- `reset_session()` creates a fresh `session_id`; do not carry continuity over.
- `switch_session()` should naturally reuse the target session's continuity record because continuity is keyed by `target_session_id`.

**Step 5: Re-run the targeted tests**

Run:

```bash
scripts/run_tests.sh tests/gateway/test_session.py -v
```

Expected: PASS.

**Step 6: Commit**

```bash
git add gateway/session.py tests/gateway/test_session.py
git commit -m "feat: persist gateway runtime continuity bindings"
```


### Task 2: Resolve Start vs Resume in Gateway Turn Dispatch

**Files:**
- Modify: `gateway/run.py`
- Test: `tests/gateway/test_mente_task_bridge.py`
- Create: `tests/gateway/test_gateway_runtime_continuity.py`

**Step 1: Write failing gateway dispatch tests**

Add narrow tests for the turn planner before touching implementation:

```python
def test_gateway_turn_without_continuity_uses_sessionful_start_with_seeded_history(...):
    ...
    assert mente_run.call_args.kwargs["execution_mode"] is ExecutionMode.SESSIONFUL
    assert mente_run.call_args.kwargs["execution_session"] == ExecutionSession(mode=SessionMode.START)
    assert mente_run.call_args.kwargs["fallback_history_fact"].startswith("Conversation history (JSON):")


def test_gateway_turn_with_active_continuity_uses_resume_without_history_replay(...):
    ...
    assert mente_run.call_args.kwargs["execution_session"] == ExecutionSession(
        mode=SessionMode.RESUME,
        continuity_id="thread-123",
    )
    assert mente_run.call_args.kwargs["fallback_history_fact"] is None
```

**Step 2: Run the new gateway-focused tests**

Run:

```bash
scripts/run_tests.sh tests/gateway/test_mente_task_bridge.py tests/gateway/test_gateway_runtime_continuity.py -v
```

Expected: failures because `_run_mente_gateway_turn()` and caller sites do not yet pass continuity controls.

**Step 3: Add a small gateway continuity planner**

In `gateway/run.py`, add a helper near `_run_mente_gateway_turn()` that resolves:

```python
def _resolve_gateway_runtime_continuity_plan(
    session_entry,
    history: list[dict[str, Any]],
    continuity_payload: dict[str, Any] | None,
) -> dict[str, Any]:
    ...
```

Required behavior:
- No continuity + empty history: `SESSIONFUL + START`, no transcript replay.
- No continuity + non-empty history: `SESSIONFUL + START`, seed transcript replay once.
- Active continuity: `SESSIONFUL + RESUME`, no transcript replay.
- Invalidated continuity: treat as no continuity, but seed transcript replay if history exists.

**Step 4: Thread the plan into `_run_mente_gateway_turn()`**

Update the gateway execution call to pass:
- `execution_mode`
- `execution_session`
- `fallback_history_fact`
- `replay_history_in_memory_facts` (boolean, if helpful for bridge readability)

After a successful response, if `result.metadata["execution_session"]` contains a non-empty `continuity_id` and no fallback status, bind it back into the session store.

**Step 5: Handle fallback/invalidation bookkeeping**

When Mente returns:
- `continuity_status == "resumed"` or `"started"` with a `continuity_id`: update the binding as active.
- `continuity_status == "fallback_stateless"` for a previous resume: invalidate the prior binding with the reported `fallback_reason`.
- `continuity_status == "missing_continuity_id"` after a start: leave the session without an active binding and log the miss.

**Step 6: Re-run the targeted gateway tests**

Run:

```bash
scripts/run_tests.sh tests/gateway/test_mente_task_bridge.py tests/gateway/test_gateway_runtime_continuity.py -v
```

Expected: PASS.

**Step 7: Commit**

```bash
git add gateway/run.py tests/gateway/test_mente_task_bridge.py tests/gateway/test_gateway_runtime_continuity.py
git commit -m "feat: route gateway turns through runtime continuity planner"
```


### Task 3: Extend the Mente Gateway Bridge Contract

**Files:**
- Modify: `mente/integrations/bridge.py`
- Test: `tests/mente/test_hermes_integration.py`

**Step 1: Write failing bridge tests**

Add tests around `build_gateway_task()` and `run_gateway_task()`:

```python
def test_build_gateway_task_accepts_sessionful_start_without_replay(tmp_path):
    task = build_gateway_task(
        ...,
        execution_mode=ExecutionMode.SESSIONFUL,
        execution_session=ExecutionSession(mode=SessionMode.START),
        fallback_history_fact=None,
    )
    assert task.execution_mode is ExecutionMode.SESSIONFUL
    assert task.execution_session.mode is SessionMode.START
    assert not any(f.startswith("Conversation history (JSON):") for f in task.memory_facts)


def test_build_gateway_task_includes_fallback_history_fact_when_requested(tmp_path):
    task = build_gateway_task(
        ...,
        execution_mode=ExecutionMode.SESSIONFUL,
        execution_session=ExecutionSession(mode=SessionMode.RESUME, continuity_id="thread-1"),
        fallback_history_fact="Conversation history (JSON):\n[]",
    )
    assert "fallback_history_fact" in task.metadata
```

**Step 2: Run the bridge tests and confirm failure**

Run:

```bash
scripts/run_tests.sh tests/mente/test_hermes_integration.py -v
```

Expected: failures because `build_gateway_task()` currently hard-codes `STATELESS` and always replays history into `memory_facts`.

**Step 3: Extend `build_gateway_task()` and `run_gateway_task()`**

Add optional parameters:

```python
execution_mode: ExecutionMode | str | None = None
execution_session: ExecutionSession | dict[str, Any] | None = None
fallback_history_fact: str | None = None
replay_history_in_memory_facts: bool = True
```

Use the same continuity normalization helper pattern already used for `api_server`.

Required behavior:
- Do not append transcript history to `memory_facts` when `replay_history_in_memory_facts=False`.
- Store `fallback_history_fact` in `task.metadata`, not normal `memory_facts`.
- Preserve current gateway metadata fields such as `session_key`, `chat_id`, and `thread_id`.

**Step 4: Re-run the bridge tests**

Run:

```bash
scripts/run_tests.sh tests/mente/test_hermes_integration.py -v
```

Expected: PASS.

**Step 5: Commit**

```bash
git add mente/integrations/bridge.py tests/mente/test_hermes_integration.py
git commit -m "feat: add gateway continuity controls to mente bridge"
```


### Task 4: Teach `CodexExecutor` to Retry with Transcript Replay

**Files:**
- Modify: `mente/executors/codex.py`
- Modify: `mente/executors/prompting.py`
- Test: `tests/mente/test_codex_executor.py`

**Step 1: Write failing executor fallback tests**

Add a dedicated test for resume failure replay:

```python
def test_codex_executor_resume_failure_retries_stateless_with_fallback_history(monkeypatch, tmp_path):
    monkeypatch.setenv("MENTE_SESSIONFUL_EXECUTION_ENABLED", "1")
    payloads = []

    class _Runner:
        def run(self, *, payload, session, runtime_config):
            payloads.append((payload.prompt, session.mode))
            if session.mode is KernelSessionMode.SESSION:
                return KernelExecutionResult(
                    status="failed",
                    assistant_summary="thread not found",
                    backend_failure="thread_not_found",
                )
            return KernelExecutionResult(status="success", assistant_summary="fallback ok")

    request = ExecutionRequest(
        ...,
        execution_mode=ExecutionMode.SESSIONFUL,
        execution_session=ExecutionSession(mode=SessionMode.RESUME, continuity_id="thread-stale"),
        metadata={
            "source": "gateway",
            "fallback_history_fact": "Conversation history (JSON):\\n[...]",
        },
        tool_policy={"session_capable": True},
    )
```

Assert that the second prompt includes the fallback history fact, not just the original memory facts.

**Step 2: Run the executor tests and confirm failure**

Run:

```bash
scripts/run_tests.sh tests/mente/test_codex_executor.py -v
```

Expected: failure because the existing stateless retry reuses the same request and cannot recover replay context.

**Step 3: Implement fallback-request synthesis**

In `mente/executors/codex.py`, add a helper:

```python
def _build_resume_fallback_request(self, request: ExecutionRequest) -> ExecutionRequest:
    ...
```

Behavior:
- Copy the request.
- Force `execution_mode=STATELESS`.
- Clear `execution_session`.
- Append `metadata["fallback_history_fact"]` into `memory_facts` if present and not already injected.

Use this helper only for bounded resume failures.

**Step 4: Stabilize prompt ordering**

While touching executor prompt behavior, reorder `render_execution_prompt()` to keep the stable scaffold first and the dynamic user request last:

```python
lines = [
    f"Objective: {request.objective}",
    f"Task Type: {request.task_type}",
]
...
lines.extend(response_contract_lines)
lines.append(f"User Request: {request.user_request}")
```

This keeps more of the prompt prefix stable across turns and across seeded fallback requests.

**Step 5: Add/adjust prompt tests**

Update tests so they explicitly assert:
- no regression in prompt fingerprint determinism for identical requests
- `User Request:` appears after `Memory Facts:` and `Response Contract:`

**Step 6: Re-run executor tests**

Run:

```bash
scripts/run_tests.sh tests/mente/test_codex_executor.py tests/mente/test_kernel_runtime_protocol.py -v
```

Expected: PASS.

**Step 7: Commit**

```bash
git add mente/executors/codex.py mente/executors/prompting.py tests/mente/test_codex_executor.py tests/mente/test_kernel_runtime_protocol.py
git commit -m "feat: replay transcript on runtime continuity fallback"
```


### Task 5: Add Gateway Continuity Feature Flags and Source Gating

**Files:**
- Modify: `mente/feature_flags.py`
- Test: `tests/mente/test_codex_executor.py`
- Test: `tests/gateway/test_gateway_runtime_continuity.py`

**Step 1: Write failing feature-flag tests**

Add tests that pin gateway rollout separately from existing API server rollout:

```python
def test_gateway_continuity_disabled_leaves_gateway_stateless(monkeypatch, tmp_path):
    monkeypatch.delenv("MENTE_GATEWAY_CONTINUITY_ENABLED", raising=False)
    ...
    assert captured["session"].mode is KernelSessionMode.STATELESS


def test_gateway_continuity_enabled_allows_gateway_source(monkeypatch, tmp_path):
    monkeypatch.setenv("MENTE_SESSIONFUL_EXECUTION_ENABLED", "1")
    monkeypatch.setenv("MENTE_SESSIONFUL_EXECUTION_SOURCES", "api_server,gateway")
    monkeypatch.setenv("MENTE_GATEWAY_CONTINUITY_ENABLED", "1")
```

**Step 2: Run the flag-sensitive tests**

Run:

```bash
scripts/run_tests.sh tests/mente/test_codex_executor.py tests/gateway/test_gateway_runtime_continuity.py -v
```

Expected: failures because there is no gateway-specific continuity gate yet.

**Step 3: Implement the gateway continuity gate**

Add helper(s) such as:

```python
def is_gateway_runtime_continuity_enabled(...): ...
```

Use them in gateway dispatch, not in the generic executor, so API server behavior remains unchanged.

Required semantics:
- `MENTE_SESSIONFUL_EXECUTION_ENABLED` remains the outer master switch.
- `MENTE_GATEWAY_CONTINUITY_ENABLED` controls whether gateway even asks for continuity.
- `MENTE_SESSIONFUL_EXECUTION_SOURCES` must still include `gateway` before executor actually resumes.

**Step 4: Re-run the flag-sensitive tests**

Run:

```bash
scripts/run_tests.sh tests/mente/test_codex_executor.py tests/gateway/test_gateway_runtime_continuity.py -v
```

Expected: PASS.

**Step 5: Commit**

```bash
git add mente/feature_flags.py tests/mente/test_codex_executor.py tests/gateway/test_gateway_runtime_continuity.py
git commit -m "feat: gate gateway runtime continuity rollout"
```


### Task 6: Invalidate Continuity on Transcript-Rewriting Commands

**Files:**
- Modify: `gateway/run.py`
- Modify: `gateway/session.py`
- Test: `tests/gateway/test_retry_replacement.py`
- Test: `tests/gateway/test_compress_command.py`
- Create: `tests/gateway/test_gateway_runtime_continuity_invalidation.py`

**Step 1: Write failing invalidation tests**

Add explicit tests for the commands that rewrite history:

```python
@pytest.mark.asyncio
async def test_retry_invalidates_runtime_continuity_before_replay(...):
    ...
    runner.session_store.invalidate_runtime_continuity.assert_called_once_with(
        "test-session",
        reason="retry_rewrite",
    )


@pytest.mark.asyncio
async def test_compress_invalidates_runtime_continuity_after_transcript_rewrite(...):
    ...
    runner.session_store.invalidate_runtime_continuity.assert_called_once_with(
        "sess-1",
        reason="compress_rewrite",
    )
```

Also add tests for `/undo` and any helper that calls `rewrite_transcript()` directly.

**Step 2: Run the invalidation tests**

Run:

```bash
scripts/run_tests.sh tests/gateway/test_retry_replacement.py tests/gateway/test_compress_command.py tests/gateway/test_gateway_runtime_continuity_invalidation.py -v
```

Expected: failures because rewrite paths do not currently touch continuity state.

**Step 3: Invalidate continuity in all transcript-mutating flows**

Touch these sites in `gateway/run.py`:
- `_handle_retry_command()`
- `_handle_undo_command()`
- `_handle_compress_command()`
- any other direct `rewrite_transcript()` callers found during implementation

And consider adding a helper:

```python
def _invalidate_runtime_continuity_for_session(self, session_id: str, *, reason: str) -> None:
    ...
```

Do not silently clear the continuity on simple `append_to_transcript()` paths.

**Step 4: Keep `switch_session()` and `reset_session()` semantics clean**

Ensure:
- `/new` or session reset simply lands on a fresh `session_id` with no active continuity.
- `/resume`/session switch picks up the target session's existing continuity record without re-binding it manually.

**Step 5: Re-run the invalidation tests**

Run:

```bash
scripts/run_tests.sh tests/gateway/test_retry_replacement.py tests/gateway/test_compress_command.py tests/gateway/test_gateway_runtime_continuity_invalidation.py -v
```

Expected: PASS.

**Step 6: Commit**

```bash
git add gateway/run.py gateway/session.py tests/gateway/test_retry_replacement.py tests/gateway/test_compress_command.py tests/gateway/test_gateway_runtime_continuity_invalidation.py
git commit -m "fix: invalidate runtime continuity on transcript rewrites"
```


### Task 7: End-to-End Verification and Rollout Safety

**Files:**
- Modify if needed: `tests/gateway/test_mente_task_bridge.py`
- Modify if needed: `tests/mente/test_hermes_integration.py`
- Optional docs note if rollout env vars need operator guidance: `docs/plans/2026-05-07-gateway-runtime-continuity-implementation.md`

**Step 1: Run the focused regression suite**

Run:

```bash
scripts/run_tests.sh \
  tests/gateway/test_session.py \
  tests/gateway/test_mente_task_bridge.py \
  tests/gateway/test_gateway_runtime_continuity.py \
  tests/gateway/test_gateway_runtime_continuity_invalidation.py \
  tests/gateway/test_retry_replacement.py \
  tests/gateway/test_compress_command.py \
  tests/mente/test_hermes_integration.py \
  tests/mente/test_codex_executor.py \
  tests/mente/test_kernel_runtime_protocol.py \
  -v
```

Expected: PASS.

**Step 2: Run one broader gateway slice**

Run:

```bash
scripts/run_tests.sh tests/gateway/ -v --tb=short
```

Expected: PASS, or only pre-existing unrelated failures.

**Step 3: Run one broader Mente slice**

Run:

```bash
scripts/run_tests.sh tests/mente/ -v --tb=short
```

Expected: PASS, or only pre-existing unrelated failures.

**Step 4: Verify runtime command shape locally through unit coverage**

Pay special attention to:
- `SESSIONFUL + START` gateway path creates a usable handoff
- `SESSIONFUL + RESUME` gateway path suppresses transcript replay
- resume failure produces a stateless retry whose prompt includes `fallback_history_fact`

If any of those only exist implicitly, add one more targeted test before merging.

**Step 5: Final commit**

```bash
git add gateway/session.py gateway/run.py mente/integrations/bridge.py mente/executors/codex.py mente/executors/prompting.py mente/feature_flags.py tests/gateway tests/mente
git commit -m "feat: add gateway runtime continuity with transcript fallback"
```


### Notes for Execution

- Prefer new targeted test files over overloading already huge ones if readability drops.
- Use `scripts/run_tests.sh`, not bare `pytest`.
- Do not delete transcript replay support; narrow it to seeded-start and stateless-fallback paths.
- Keep continuity binding keyed by `session_id`; this is what makes `switch_session()` naturally restore prior runtime continuity.
- Treat `continuity_status == "fallback_stateless"` as a first-class operational signal, not just a debug field.
