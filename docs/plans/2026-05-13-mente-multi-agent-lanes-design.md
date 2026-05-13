# Mente Multi-Agent Lanes Design

## Summary

This design introduces a **director + specialist lanes** architecture for Mente without turning every user turn into two serial LLM calls.

The core decision is:

- Keep a lightweight **director layer** as the user-facing coordinator.
- Route obvious work with **deterministic rules first**, not with a heavyweight "manager model".
- Maintain **independent continuity lanes** for engineering, research, writing, config/admin, and lightweight conversation.
- Require specialists to report progress via **structured events**, then let the director surface those events to the user.

This design is intended to reduce prompt bloat and context contamination while preserving the current Codex runtime path for real work.

## Why This Design

The performance problem is not solved by "having more agents" by itself. If Mente always does:

1. run a manager model,
2. let that manager think,
3. then run a specialist model,

the system usually becomes slower, not faster.

The useful part of the OpenClaw-style pattern is **separation of responsibilities and context lanes**, not mandatory double-inference.

For Mente, the right translation is:

- the **director** is mostly a control plane concern;
- the **specialist** is the only heavy runtime when a concrete task needs it;
- **casual dialogue** stays in a thin conversation lane;
- **engineering continuity** stays in an engineering lane and is not polluted by research/writing/chat turns.

This directly attacks the current problems:

- non-engineering turns inheriting engineering prompt pressure;
- one continuity thread carrying unrelated work across domains;
- progress reporting requiring another free-form model summary instead of a structured event stream.

## Goals

- Reduce latency for non-engineering dialogue without bypassing Codex runtime.
- Isolate continuity across domains so one thread does not accumulate all user history.
- Preserve strong specialist behavior for coding, research, writing, and config tasks.
- Make progress updates Mente-owned and structured instead of model-invented.
- Reuse the current `task_profile`, `execution_session`, `workflow_contract`, and gateway/TUI continuity seams.

## Non-Goals

- Do not introduce a second mandatory LLM pass for every turn.
- Do not build a recursive autonomous multi-agent swarm.
- Do not replace current specialist runtime behavior for engineering tasks.
- Do not push all routing into model judgment when deterministic routing is available.

## Recommended Architecture

### 1. Director Layer

The director is the user-facing coordinator, but it should be implemented primarily as a **bridge/runtime orchestration layer**, not as a required extra model turn.

Responsibilities:

- interpret the incoming user turn;
- decide whether the turn is:
  - direct conversation,
  - engineering,
  - research,
  - writing/content,
  - config/admin,
  - artifact follow-up / delivery;
- choose the correct continuity lane;
- aggregate structured progress events from specialists;
- format user-visible updates and final responses.

The director should use this routing order:

1. control commands and approvals;
2. explicit task-profile rules and heuristics;
3. specialist lane reuse when an active lane already exists;
4. thin runtime classification only for genuinely ambiguous turns.

This means the "director" exists conceptually on every turn, but it does **not** imply a separate heavy model invocation on every turn.

### 2. Specialist Lanes

Define a bounded role set:

- `director_conversation`
- `engineering`
- `research`
- `writing`
- `config_admin`

Later expansion is possible, but these five roles are enough for the current product.

Each lane owns:

- its own continuity id;
- its own prompt style / base instructions;
- its own task-profile defaults;
- its own progress semantics.

Examples:

- `director_conversation`: thin prompt, casual Q&A, lightweight product explanations.
- `engineering`: current coding/debugging/config-change heavy path.
- `research`: market research, industry analysis, competitor analysis.
- `writing`: drafting, rewriting, publishing prep, marketing copy.
- `config_admin`: operational changes to Mente config, auth, gateway, runtime provider settings.

## Session and Continuity Model

Today the gateway and TUI effectively maintain **one runtime continuity binding per user session**. That is the main bottleneck for this architecture.

The key change is to move from:

- `session_id -> one continuity payload`

to:

- `session_id -> lane registry`
- `lane_key -> continuity payload`

Recommended lane payload shape:

```json
{
  "runtime": "mente_codex_executor",
  "status": "active",
  "continuity_id": "thread-123",
  "lane": "engineering",
  "task_profile": "engineering",
  "updated_at": "2026-05-13T10:30:00+08:00"
}
```

Recommended lane keys:

- `director`
- `engineering`
- `research`
- `writing`
- `config_admin`

Important behavior:

- casual chat uses the `director` lane;
- coding turns resume the `engineering` lane if active;
- research turns resume the `research` lane if active;
- writing turns resume the `writing` lane if active;
- some profiles, such as artifact delivery or one-shot config changes, may explicitly start fresh or invalidate a lane on completion.

This keeps unrelated turns from polluting each other while still preserving continuity where it actually matters.

## Routing Strategy

### Deterministic First

Routing should start with Mente-owned logic in `bridge.py` or a nearby routing module.

Strong deterministic signals:

- explicit task-profile hints already inferred today;
- known config/admin action + target pairs;
- known publishing / delivery requests;
- code-oriented language plus repo/config/file/test/command vocabulary;
- research/analysis/market/competitor language;
- pure greeting / identity / product-explanation turns.

### Thin Classification Only When Needed

When deterministic rules cannot confidently decide, the system may run a **thin classifier prompt**. This classifier should not be the full engineering runtime prompt. It should return a small structured result such as:

```json
{
  "lane": "research",
  "confidence": "medium",
  "reason": "market-analysis phrasing without coding signals"
}
```

This classifier is a fallback, not the primary path.

### Active Lane Reuse

If the user is clearly continuing existing engineering/research/writing work, lane reuse should win over generic classification.

Examples:

- "继续"
- "按刚才那个方案改"
- "把报告整理成对比表"
- "把文案再改短一点"

This should resolve against the most recent active lane snapshot before defaulting back to `director_conversation`.

## Prompt Strategy

The prompt strategy should match the lane model.

### Director Conversation Lane

Use the thinnest prompt in the system:

- concise reply policy;
- answer in the user's language;
- do not invent prior context;
- use tools only if necessary.

No engineering execution scaffolding should be injected here.

### Engineering Lane

Keep the current stronger coding prompt shape, because this lane is where correctness and workflow discipline matter.

### Research Lane

Use a focused research prompt:

- gather, compare, synthesize;
- prefer evidence and direct conclusions;
- avoid coding-oriented execution guidance unless explicitly needed.

### Writing Lane

Use a focused writing/content prompt:

- draft, rewrite, structure, audience fit;
- preserve tone constraints;
- support artifact generation and publication handoff.

### Config/Admin Lane

Keep the existing config-admin specialized prompt.

This separation means non-engineering turns stop paying for engineering prompt overhead, while specialists keep the guardrails they actually need.

## Structured Progress Reporting

Specialists must report progress through structured events, not free-form manager summaries.

Recommended event envelope:

```json
{
  "event_type": "lane.progress",
  "lane": "engineering",
  "task_id": "mente_gateway_abc123",
  "status": "running",
  "headline": "Running targeted tests",
  "detail": "tests/mente/test_bridge_integration.py -q",
  "artifacts": [],
  "changed_files": [],
  "timestamp": "2026-05-13T10:35:00+08:00"
}
```

Minimum event types:

- `lane.started`
- `lane.progress`
- `lane.blocked`
- `lane.completed`
- `lane.failed`

The director consumes these events and renders user-visible updates such as:

- "工程部正在跑桥接层回归测试"
- "市场部已完成竞品信息收集，正在整理对比结论"

The user-visible text can be template-based first. It does not need another LLM call unless a richer natural-language summary is explicitly required.

## Integration With Existing Mente Seams

This design intentionally reuses current implementation surfaces.

### `task_profile`

Extend `task_profile` from a narrow workflow hint into a broader **lane selector** input.

Keep workflow-level profiles such as:

- `content_publishing`
- `artifact_delivery`
- `config_admin`
- `deep_research`

Add lane metadata alongside them:

- `metadata.lane = "engineering" | "research" | "writing" | "config_admin" | "director"`

### `workflow_contract`

Add a `director` / `lane` section to the existing machine-readable contract so downstream code knows:

- which lane handled the turn;
- whether structured progress is expected;
- whether continuity is lane-scoped;
- whether the lane is resumable or one-shot.

### `execution_session`

Do not change the transport contract itself. Instead, change how continuity ids are looked up and persisted:

- current: one continuity binding per session;
- target: one continuity binding per `(session_id, lane)`.

### Gateway and TUI

Both already have continuity planning and execution handoff seams. The change is mainly in the lookup key and the routing layer that selects the lane before calling `run_gateway_task` / `run_tui_task`.

## Failure Handling

Failure behavior should be explicit and lane-aware.

- If routing confidence is low, the director asks a short clarifying question.
- If a specialist lane fails, the director returns the blocker and keeps the lane state for possible retry.
- If a lane becomes stale, invalidate only that lane's continuity, not the whole user session.
- If a workflow completes a one-shot profile, invalidate that lane on success when appropriate.

This prevents a failed research turn from breaking engineering continuity, and vice versa.

## Expected Performance Impact

This design improves speed in three ways:

1. non-engineering dialogue stays in a thin lane with a much smaller prompt;
2. engineering continuity stops carrying research/writing/chat baggage;
3. progress reporting becomes structured and Mente-owned instead of requiring another summarization pass.

It does **not** improve speed by adding more reasoning hops. The performance gain comes from **lane isolation and prompt specialization**.

## Implementation Phases

### Phase 1: Lane Metadata and Continuity Registry

- Introduce lane constants and routing result model.
- Extend continuity persistence to `session + lane`.
- Keep existing runtime behavior otherwise unchanged.

### Phase 2: Deterministic Router

- Add a Mente-owned router ahead of `build_gateway_task` / `build_tui_task`.
- Populate `metadata.lane` and lane-aware `task_profile`.
- Route casual dialogue to `director_conversation`.

### Phase 3: Specialist Prompt Separation

- Finalize thin prompt for `director_conversation`.
- Add research and writing specialist prompt profiles.
- Keep engineering and config-admin prompts specialized.

### Phase 4: Structured Progress Events

- Normalize executor events into lane events.
- Teach gateway/TUI to surface lane progress through the director voice.

### Phase 5: Lane Reuse and Active-Task Follow-up

- Prefer active lane reuse for continuation turns.
- Add lane-aware recent-task snapshots and follow-up routing.

## Testing Strategy

Required test coverage:

- routing tests for lane selection;
- continuity tests proving per-lane persistence and invalidation;
- prompt tests proving casual dialogue uses thin prompts while engineering keeps full prompts;
- gateway/TUI integration tests proving correct lane reuse;
- progress event translation tests proving specialists can report to the director without extra model summarization;
- regression tests proving one lane failure does not poison another lane.

## Recommendation

Implement this as a **lane-based orchestration upgrade**, not as a mandatory manager-model architecture.

The practical product story can still be expressed in your preferred metaphor:

- 司礼监 = director layer
- 工程部 = engineering lane
- 市场部 = research lane
- 礼部 = writing lane
- 运维/内务府 = config-admin lane

But internally, the system should stay:

- deterministic-first,
- continuity-per-lane,
- structured-progress-first,
- heavy runtime only where heavy runtime is actually needed.

That is the version most likely to reduce context pressure and improve user-perceived speed without making the architecture slower or more fragile.
