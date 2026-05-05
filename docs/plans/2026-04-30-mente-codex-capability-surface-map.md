# Mente ↔ Vendored Codex Capability Surface Map

## Goal

Freeze the **source of truth** for Phase C5 capability exposure around the vendored Codex snapshot rather than a Mente-local replacement registry.

After Phase C4, execution already enters vendored Codex through the bridge-selected vendored front door. Phase C5 keeps that cutover intact and only maps the capability surface that Mente may filter from the outside.

## Source-of-truth files

The authoritative vendored surfaces for this phase are:

- `kernel/codex/upstream/codex-rs/tools/src/lib.rs`
- `kernel/codex/upstream/codex-rs/plugin/src/lib.rs`
- `kernel/codex/upstream/codex-rs/skills/src/lib.rs`
- `kernel/codex/upstream/sdk/python/src/codex_app_server/`

The bridge helper `kernel/codex/bridge/tool_surface.py` must read and expose these vendored surfaces. It is intentionally a thin map, not a replacement registry.

## Native tool surface (vendored Codex owned)

`kernel/codex/upstream/codex-rs/tools/src/lib.rs` re-exports the vendored upstream tool surface. The Phase C5 bridge map resolves native names from the vendored `tools/src/` sources and keeps that list separate from Mente bridge tools.

Current vendored native tool names surfaced through the bridge map:

- `apply_patch`
- `close_agent`
- `create_goal`
- `exec_command`
- `followup_task`
- `get_goal`
- `image_generation`
- `list_agents`
- `list_dir`
- `list_mcp_resource_templates`
- `list_mcp_resources`
- `local_shell`
- `read_mcp_resource`
- `report_agent_job_result`
- `request_permissions`
- `request_user_input`
- `resume_agent`
- `send_input`
- `send_message`
- `shell`
- `shell_command`
- `spawn_agent`
- `spawn_agents_on_csv`
- `test_sync_tool`
- `tool_search`
- `tool_suggest`
- `update_goal`
- `update_plan`
- `view_image`
- `wait_agent`
- `web_search`
- `write_stdin`

These names are vendored-upstream owned. Mente may later filter visibility, but Mente does not redefine them.

## Plugin hook surface (vendored Codex owned)

`kernel/codex/upstream/codex-rs/plugin/src/lib.rs` is the upstream plugin-facing hook/export surface currently mapped for C5. Relevant vendored identifiers include:

- `PluginHookSource`
- `PluginCapabilitySummary`
- `PluginTelemetryMetadata`
- `PluginLoadOutcome`
- `LoadedPlugin`
- `EffectiveSkillRoots`
- `AppConnectorId`
- `PluginId`
- `mention_syntax`
- `plugin_namespace_for_skill_path`
- `prompt_safe_plugin_description`

For C5, plugin hooks remain Codex-owned capability. Product-specific enablement and policy still live outside the kernel.

## Skill loading hooks (vendored Codex owned)

`kernel/codex/upstream/codex-rs/skills/src/lib.rs` is the upstream skill-loading seam currently relevant to Mente integration. The mapped exported functions are:

- `system_cache_root_dir`
- `install_system_skills`

This means embedded/system skill installation semantics belong to vendored Codex, not to a Mente-local skill loader rewrite.

## Python-facing app-server touchpoints

The Python SDK touchpoints relevant to Mente integration are under `kernel/codex/upstream/sdk/python/src/codex_app_server/`.

Primary touchpoints mapped in C5:

- `kernel/codex/upstream/sdk/python/src/codex_app_server/__init__.py`
- `kernel/codex/upstream/sdk/python/src/codex_app_server/api.py`
- `kernel/codex/upstream/sdk/python/src/codex_app_server/client.py`
- `kernel/codex/upstream/sdk/python/src/codex_app_server/async_client.py`
- `kernel/codex/upstream/sdk/python/src/codex_app_server/models.py`
- `kernel/codex/upstream/sdk/python/src/codex_app_server/_run.py`

Notable Python-facing exported types include `Codex`, `AsyncCodex`, `Thread`, `TurnHandle`, `AppServerClient`, `AsyncAppServerClient`, `RunResult`, `SkillInput`, `MentionInput`, and the generated thread/turn notification models exposed from `__init__.py`.

For C5, these are documented as integration touchpoints only. Product orchestration still belongs to Mente.

## Explicit exclusion: Mente bridge tools

Mente bridge tools stay outside the vendored native surface.

They remain product-owned in `mente/executors/bridge_tools.py`, including:

- `mente_memory_query`
- `mente_memory_append`
- `mente_task_lookup`
- `mente_schedule_cron`
- `mente_gateway_send`
- `mente_session_notify`

They are **not** merged into `kernel/codex/upstream/`, **not** appended to the vendored native registry, and **not** the source of truth for native capability discovery.

## Boundary summary

- Vendored Codex owns native tools, plugin hooks, skill loading hooks, and app-server SDK surfaces.
- `kernel/codex/bridge/tool_surface.py` documents and exposes those vendored surfaces.
- Mente remains responsible only for outer policy, ingress decisions, and product integration.
- Bridge tools stay outside the kernel and outside the vendored native capability surface.
