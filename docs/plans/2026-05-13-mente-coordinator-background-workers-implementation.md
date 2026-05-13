# Mente Coordinator Background Workers Implementation Plan

> **For Mente:** REQUIRED SKILL: Use `executing-plans` to implement this plan task-by-task.

**Goal:** Make the user-facing coordinator stay responsive while complex work runs in background specialist workers with structured progress reporting and status follow-up.

**Architecture:** Keep deterministic-first lane routing, but split every complex turn into two phases: a thin coordinator turn that classifies, delegates, and answers the user immediately, and a background worker run that owns execution for one lane or skill workflow. Reuse the current lane/task-profile system where possible, avoid a wide rename of internal `director` identifiers in phase 1, and add an explicit session job registry plus task event log so the coordinator can answer “what’s happening now?” without resuming the worker prompt.

**Tech Stack:** Python, SQLite task/session state, gateway session store, existing Mente bridge/orchestrator/executor stack, existing lane progress events.

---

## Naming

- Public product term: `Coordinator`
- Background execution term: `Worker`
- Internal compatibility note: keep the existing lane key `director` in phase 1 where changing it would create broad churn, but treat it as the coordinator lane in prompts, docs, and user-visible status text.

## Target Behavior

1. A complex request like “深度研究某产品” should be accepted by the coordinator, delegated to the `research` worker, and acknowledged immediately.
2. A skill-oriented request like “调用技能做 xxx” should be resolved into either:
   - one explicit `skill_ref` + owning lane, or
   - one clarification request from the coordinator when the skill target is ambiguous.
3. While a worker runs, the user can still ask:
   - “现在进度”
   - “暂停”
   - “继续”
   - “改成先做 A”
   - “顺便再加一个对比维度”
4. Those follow-up turns should hit the coordinator first, not block behind the worker execution lock.
5. Worker progress must be stored as structured events and surfaced periodically through gateway/TUI without requiring a free-form LLM summary every time.

## Scope Boundaries

- Do not build a recursive swarm.
- Do not replace the current Codex executor path for actual work.
- Do not rename every `director` code identifier in the same change.
- Do not make every turn pay for two heavy model calls.

## Current Constraints To Preserve

- Routing already exists in [`mente/integrations/bridge.py`](../..//mente/integrations/bridge.py).
- Lane-to-agent mapping already exists in [`mente/agents/registry.yaml`](../..//mente/agents/registry.yaml).
- Runtime continuity already supports one payload per lane in gateway/TUI state.
- Progress events already exist in [`mente/execution_events.py`](../..//mente/execution_events.py), but they are transient and not yet persisted as a first-class event log.
- Gateway still has one active-session guard in [`gateway/platforms/base.py`](../..//gateway/platforms/base.py), which is the main blocker for a always-responsive coordinator.

### Task 1: Introduce explicit coordinator/worker dispatch models

**Files:**
- Modify: [`mente/task_core/models.py`](/root/code/Mente/mente/task_core/models.py)
- Test: `tests/mente/test_task_models.py`

**Step 1: Write the failing tests**

Add tests for:
- `TaskRole` enum normalization for `coordinator` and `worker`
- `DispatchMode` enum normalization for `inline`, `delegate_background`, `delegate_foreground`
- `Task` carrying `parent_task_id`, `job_id`, `role`, `dispatch_mode`, `worker_lane`, `worker_skill_refs`
- `ExecutionResult.metadata["job_state"]` shape validation helper if added

**Step 2: Run test to verify it fails**

Run: `scripts/run_tests.sh tests/mente/test_task_models.py`

Expected: FAIL because the new fields and enums do not exist.

**Step 3: Write minimal implementation**

Add to `models.py`:
- `TaskRole(StrEnum): COORDINATOR, WORKER`
- `DispatchMode(StrEnum): INLINE, DELEGATE_BACKGROUND, DELEGATE_FOREGROUND`
- new optional fields on `Task` and `ExecutionRequest`:
  - `parent_task_id`
  - `job_id`
  - `role`
  - `dispatch_mode`
  - `worker_lane`
  - `worker_skill_refs`

Default behavior:
- legacy callers get `role=worker`
- legacy callers get `dispatch_mode=inline`

**Step 4: Run test to verify it passes**

Run: `scripts/run_tests.sh tests/mente/test_task_models.py`

Expected: PASS

### Task 2: Add a first-class session job registry and task event log

**Files:**
- Modify: [`mente/task_core/repository.py`](/root/code/Mente/mente/task_core/repository.py)
- Modify: [`gateway/session.py`](/root/code/Mente/gateway/session.py)
- Create: `tests/mente/test_task_repository_jobs.py`
- Create: `tests/gateway/test_session_job_registry.py`

**Step 1: Write the failing tests**

Add tests for:
- binding one active job per `session_id + lane`
- listing active jobs across lanes for one session
- persisting progress events per `task_id`
- clearing or superseding one active job when completed/cancelled
- reading the latest progress summary without loading the full task payload

**Step 2: Run tests to verify they fail**

Run: `scripts/run_tests.sh tests/mente/test_task_repository_jobs.py tests/gateway/test_session_job_registry.py`

Expected: FAIL because the job registry and event-log APIs do not exist.

**Step 3: Write minimal implementation**

Extend SQLite state with two new tables:

- `mente_session_jobs`
  - `session_id`
  - `lane`
  - `job_id`
  - `task_id`
  - `status`
  - `summary`
  - `requested_at`
  - `updated_at`
  - `skill_refs_json`
  - `metadata_json`

- `mente_task_events`
  - `event_id`
  - `task_id`
  - `session_id`
  - `lane`
  - `event_type`
  - `payload_json`
  - `created_at`

Add repository methods:
- `bind_session_job(...)`
- `get_session_job(session_id, lane)`
- `list_session_jobs(session_id, status=None)`
- `append_task_event(...)`
- `list_task_events(task_id, limit=...)`
- `get_latest_task_event(task_id, event_type=None)`

Add session-store helpers mirroring current continuity accessors:
- `bind_session_job`
- `get_session_job`
- `list_session_jobs`
- `clear_session_job`

**Step 4: Run tests to verify they pass**

Run: `scripts/run_tests.sh tests/mente/test_task_repository_jobs.py tests/gateway/test_session_job_registry.py`

Expected: PASS

### Task 3: Split routing into dispatch decisions, not only lane decisions

**Files:**
- Modify: [`mente/integrations/bridge.py`](/root/code/Mente/mente/integrations/bridge.py)
- Create: `tests/mente/test_dispatch_routing.py`

**Step 1: Write the failing tests**

Add tests for:
- deep research -> `lane=research`, `dispatch_mode=delegate_background`
- obvious engineering change -> `lane=engineering`, `dispatch_mode=delegate_background`
- generic chat -> `lane=director`, `dispatch_mode=inline`
- explicit status follow-up -> `lane=director`, `dispatch_mode=inline`, `target_job_lane=<worker lane>`
- explicit skill request with known skill owner -> background worker
- explicit but ambiguous skill request -> inline coordinator clarification

**Step 2: Run test to verify it fails**

Run: `scripts/run_tests.sh tests/mente/test_dispatch_routing.py`

Expected: FAIL because only `ConversationRoute` exists today.

**Step 3: Write minimal implementation**

Add a new dataclass next to `ConversationRoute`:

```python
@dataclass(frozen=True)
class DispatchDecision:
    lane: str
    dispatch_mode: str
    task_profile: str | None
    skill_refs: tuple[str, ...]
    target_job_lane: str | None
    needs_clarification: bool
    reason: str
```

Add `resolve_dispatch_decision(...)` that wraps or replaces `resolve_conversation_route(...)`.

Routing rules:
- fast identity / greetings / status-only -> inline coordinator
- task-profile-backed work -> delegate background
- engineering heuristic -> delegate background
- explicit continue on an active job -> inline coordinator first, then coordinator emits control action
- classifier fallback may choose lane, but the dispatch rule is still Mente-owned:
  - `director` => inline
  - any specialist lane => delegate background

Skill handling:
- if a recognized `skill_ref` maps to one task-profile owner, delegate
- if the user says “调用技能” but no concrete skill owner is derivable, mark `needs_clarification=True`

**Step 4: Run test to verify it passes**

Run: `scripts/run_tests.sh tests/mente/test_dispatch_routing.py`

Expected: PASS

### Task 4: Add a thin coordinator runtime profile

**Files:**
- Modify: [`mente/executors/runtime_config.py`](/root/code/Mente/mente/executors/runtime_config.py)
- Modify: [`mente/agents/registry.yaml`](/root/code/Mente/mente/agents/registry.yaml)
- Test: `tests/mente/test_runtime_config.py`

**Step 1: Write the failing tests**

Add tests for:
- coordinator requests use the thin coordinator base instructions
- worker requests continue using lane-specific prompts
- internal `director` lane still resolves to the coordinator soul in phase 1

**Step 2: Run test to verify it fails**

Run: `scripts/run_tests.sh tests/mente/test_runtime_config.py -k coordinator`

Expected: FAIL because the coordinator profile does not exist.

**Step 3: Write minimal implementation**

Add one new base-instructions block:
- `MENTE_COORDINATOR_BASE_INSTRUCTIONS`

Responsibilities:
- classify
- decide whether to delegate
- acknowledge
- answer status
- collect clarifications
- never perform heavy repository work itself unless explicitly forced into inline mode

Map:
- public naming => `coordinator`
- internal lane id => keep `director` initially

**Step 4: Run test to verify it passes**

Run: `scripts/run_tests.sh tests/mente/test_runtime_config.py -k coordinator`

Expected: PASS

### Task 5: Build explicit worker tasks instead of running the ingress task directly

**Files:**
- Modify: [`mente/integrations/bridge.py`](/root/code/Mente/mente/integrations/bridge.py)
- Modify: [`mente/orchestrator/service.py`](/root/code/Mente/mente/orchestrator/service.py) only if a lightweight helper is needed
- Create: `tests/mente/test_coordinator_worker_task_building.py`

**Step 1: Write the failing tests**

Add tests for:
- one gateway ingress turn creates:
  - one coordinator task
  - one worker task for specialist execution
- worker task inherits lane, task_profile, skill_refs, workspace, continuity plan
- coordinator task stores `job_id` and linked `parent_task_id`

**Step 2: Run test to verify it fails**

Run: `scripts/run_tests.sh tests/mente/test_coordinator_worker_task_building.py`

Expected: FAIL because ingress currently creates only one task.

**Step 3: Write minimal implementation**

Add helpers:
- `build_coordinator_task(...)`
- `build_worker_task_from_dispatch(...)`
- `start_background_worker(...)`

Coordinator task:
- `role=coordinator`
- `dispatch_mode=inline` or `delegate_background`
- minimal memory facts
- no heavy execution when delegating

Worker task:
- `role=worker`
- `dispatch_mode=delegate_background`
- lane/task-profile/skill refs resolved already
- rich execution constraints as today

**Step 4: Run test to verify it passes**

Run: `scripts/run_tests.sh tests/mente/test_coordinator_worker_task_building.py`

Expected: PASS

### Task 6: Replace single active-session lock with coordinator + worker concurrency

**Files:**
- Modify: [`gateway/platforms/base.py`](/root/code/Mente/gateway/platforms/base.py)
- Modify: [`gateway/run.py`](/root/code/Mente/gateway/run.py)
- Modify: [`tui_gateway/server.py`](/root/code/Mente/tui_gateway/server.py)
- Create: `tests/gateway/test_gateway_coordinator_worker_concurrency.py`
- Create: `tests/tui/test_tui_coordinator_worker_concurrency.py`

**Step 1: Write the failing tests**

Add tests for:
- worker running in background does not block a status follow-up turn
- worker running in `research` lane does not block a new inline coordinator clarification turn
- cancel/pause commands target the active worker job without dropping the front-desk session
- second complex request in same lane either queues, supersedes, or requires confirmation according to policy

**Step 2: Run tests to verify they fail**

Run: `scripts/run_tests.sh tests/gateway/test_gateway_coordinator_worker_concurrency.py tests/tui/test_tui_coordinator_worker_concurrency.py`

Expected: FAIL because the single active-session guard still serializes the whole session.

**Step 3: Write minimal implementation**

Introduce two distinct concepts:
- `interactive coordinator turn guard`
- `background worker job registry`

Rules:
- only one coordinator turn at a time per session
- zero or more background workers, but at most one active worker per `session + lane`
- status/clarification/control turns never wait behind worker execution

Implementation approach:
- keep the existing session key
- move long-running worker execution into task-owned background jobs
- store the job handle outside `_active_sessions`
- reserve `_active_sessions` for the short coordinator turn only

**Step 4: Run tests to verify they pass**

Run: `scripts/run_tests.sh tests/gateway/test_gateway_coordinator_worker_concurrency.py tests/tui/test_tui_coordinator_worker_concurrency.py`

Expected: PASS

### Task 7: Persist and surface worker progress as coordinator-readable state

**Files:**
- Modify: [`mente/execution_events.py`](/root/code/Mente/mente/execution_events.py)
- Modify: [`mente/executors/codex.py`](/root/code/Mente/mente/executors/codex.py)
- Modify: [`gateway/run.py`](/root/code/Mente/gateway/run.py)
- Modify: [`tui_gateway/server.py`](/root/code/Mente/tui_gateway/server.py)
- Create: `tests/mente/test_execution_events_persistence.py`
- Create: `tests/gateway/test_gateway_worker_progress_updates.py`

**Step 1: Write the failing tests**

Add tests for:
- every normalized lane event is appended to `mente_task_events`
- gateway periodic progress pulls from stored event summaries, not only live stream callbacks
- completed job writes a final checkpoint summary readable by the coordinator

**Step 2: Run tests to verify they fail**

Run: `scripts/run_tests.sh tests/mente/test_execution_events_persistence.py tests/gateway/test_gateway_worker_progress_updates.py`

Expected: FAIL because current progress is transient.

**Step 3: Write minimal implementation**

When event callbacks fire:
- normalize to lane event
- persist event
- update `mente_session_jobs.summary` with a compact rolling summary

Coordinator-facing status read path should use:
- latest job state
- latest 3-5 summary items
- latest blocked reason if present

**Step 4: Run tests to verify they pass**

Run: `scripts/run_tests.sh tests/mente/test_execution_events_persistence.py tests/gateway/test_gateway_worker_progress_updates.py`

Expected: PASS

### Task 8: Add coordinator control actions for pause, cancel, reprioritize, and follow-up edits

**Files:**
- Modify: [`gateway/run.py`](/root/code/Mente/gateway/run.py)
- Modify: [`mente/integrations/bridge.py`](/root/code/Mente/mente/integrations/bridge.py)
- Possibly modify: [`tools/delegate_tool.py`](/root/code/Mente/tools/delegate_tool.py) if worker fan-out control needs an explicit contract
- Create: `tests/gateway/test_gateway_worker_controls.py`

**Step 1: Write the failing tests**

Add tests for:
- “暂停这个研究”
- “取消刚才那个任务”
- “继续跑”
- “改成先比较价格，再写结论”

Expected behavior:
- coordinator updates the job state or submits a control directive
- worker receives a resumable control instruction when supported
- if live mutation is not supported, coordinator acknowledges and starts a superseding worker task with lineage metadata

**Step 2: Run tests to verify they fail**

Run: `scripts/run_tests.sh tests/gateway/test_gateway_worker_controls.py`

Expected: FAIL because control-plane actions do not exist.

**Step 3: Write minimal implementation**

Add one `job_control` metadata contract:
- `action`: pause | cancel | resume | supersede
- `target_job_id`
- `reason`
- `new_user_request`

Do not promise in-place mutation unless the worker runtime can honor it.
Safe fallback:
- cancel old job
- start a new worker task with `supersedes_job_id`

**Step 4: Run tests to verify it passes**

Run: `scripts/run_tests.sh tests/gateway/test_gateway_worker_controls.py`

Expected: PASS

### Task 9: Make explicit skill invocation routeable and auditable

**Files:**
- Modify: [`mente/integrations/bridge.py`](/root/code/Mente/mente/integrations/bridge.py)
- Modify: [`mente/agents/registry.yaml`](/root/code/Mente/mente/agents/registry.yaml)
- Create: `tests/mente/test_skill_dispatch_resolution.py`

**Step 1: Write the failing tests**

Add tests for:
- explicit known skill request resolves to one owner lane
- explicit multiple skill refs from the same lane resolve cleanly
- explicit skills crossing lanes trigger clarification or multi-stage plan
- unknown skill request triggers coordinator clarification instead of random dispatch

**Step 2: Run tests to verify they fail**

Run: `scripts/run_tests.sh tests/mente/test_skill_dispatch_resolution.py`

Expected: FAIL because skill inference is still heuristic-only.

**Step 3: Write minimal implementation**

Add a skill ownership resolver:
- first check explicit `skill_ref`
- then known aliases
- then task-profile hints

Registry extension:
- per agent, optional `skill_owners` list

Rule:
- one request maps to one owning worker lane unless the user explicitly asks for a multi-stage workflow

**Step 4: Run tests to verify they pass**

Run: `scripts/run_tests.sh tests/mente/test_skill_dispatch_resolution.py`

Expected: PASS

### Task 10: Wire user-visible coordinator acknowledgements and status replies

**Files:**
- Modify: [`gateway/run.py`](/root/code/Mente/gateway/run.py)
- Modify: [`tui_gateway/server.py`](/root/code/Mente/tui_gateway/server.py)
- Create: `tests/gateway/test_gateway_coordinator_replies.py`

**Step 1: Write the failing tests**

Add tests for:
- complex delegated request gets immediate ack with lane + next step + job id
- status follow-up gets a concise reply from stored job progress
- blocked job gets a concise blocker summary and suggested next action
- completed job gets artifact/result summary without reopening worker context

**Step 2: Run tests to verify they fail**

Run: `scripts/run_tests.sh tests/gateway/test_gateway_coordinator_replies.py`

Expected: FAIL because replies are tied to the worker run itself today.

**Step 3: Write minimal implementation**

Coordinator reply templates:
- accepted: “已转给研究 worker，正在收集资料与形成结论。”
- running status: “当前在检索竞品资料，已完成 X/Y。”
- blocked: “卡在 API key 缺失，是否改用公开资料继续？”
- completed: “研究已完成，已生成结论与附件。”

Keep them deterministic-first. Only use a model for summarization if the stored state is insufficient.

**Step 4: Run tests to verify they pass**

Run: `scripts/run_tests.sh tests/gateway/test_gateway_coordinator_replies.py`

Expected: PASS

### Task 11: Run the integrated regression slice

**Files:**
- No code changes required

**Step 1: Run focused regression**

Run:

```bash
scripts/run_tests.sh \
  tests/mente/test_bridge_integration.py \
  tests/mente/test_runtime_config.py \
  tests/gateway/test_gateway_runtime_continuity.py \
  tests/gateway/test_gateway_coordinator_worker_concurrency.py \
  tests/gateway/test_gateway_worker_progress_updates.py \
  tests/gateway/test_gateway_worker_controls.py
```

Expected: PASS

**Step 2: Run one broader Mente/gateway slice**

Run:

```bash
scripts/run_tests.sh tests/mente/ tests/gateway/
```

Expected: PASS or a small number of unrelated pre-existing failures.

## Design Choices

### Why keep internal `director` in phase 1

- It avoids a repo-wide churn across runtime continuity, event labels, tests, and lane mappings.
- The user-visible role can already be renamed to `Coordinator`.
- After behavior is stable, a later migration can rename the internal lane key if still desirable.

### Why use one job registry instead of only task metadata

- status follow-up needs one cheap read path
- coordinator reply generation should not parse entire raw task payloads
- queueing, superseding, and control actions need one canonical current-job record per lane

### Why not let the coordinator execute “just a little”

Because that recreates the current problem. The coordinator should do only:
- classify
- clarify
- acknowledge
- summarize progress
- apply control actions

Heavy repo work, long web research, file mutation, and test runs belong to workers.

## Open Questions To Resolve During Implementation

1. Do we allow one worker per lane or one worker total per session in phase 1.
   Recommendation: one active worker per lane, multiple lanes allowed.
2. Do we queue same-lane jobs automatically or require confirmation.
   Recommendation: require confirmation when a same-lane active job already exists.
3. Do we support in-place worker mutation or always supersede with a new job.
   Recommendation: always supersede in phase 1 unless the runtime explicitly supports pause/resume mutation.

## Recommended Delivery Order

1. Task 1-3: data model + dispatch decision
2. Task 4-5: coordinator profile + worker task creation
3. Task 6-7: concurrency split + persisted progress
4. Task 8-10: control actions + user-visible replies
5. Task 11: regression sweep

## Minimal MVP Cut

If we need a smaller first landing, ship this subset:
- coordinator profile
- dispatch decision
- background worker jobs
- persisted progress summary
- status follow-up from job registry

Defer:
- pause/resume
- multi-lane concurrent workers
- cross-skill workflow composition
