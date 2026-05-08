# Mente Home Bootstrap Bypass Audit

## Scope

This audit focuses on executable code paths that can still bypass the Mente bootstrap layer and either:

1. fall back directly to `~/.hermes`, or
2. still resolve profile/runtime state through legacy Hermes-root semantics when no bootstrap has happened yet.

## Fixed In This Pass

### Main home/root resolution

- `hermes_constants.py`
  - `get_default_hermes_root()` now defaults to `~/.mente` when neither `HERMES_HOME` nor `MENTE_HOME` is set.
  - Legacy `~/.hermes` layouts still resolve correctly when explicitly active.

### Memory

- `tools/memory_tool.py`
  - `get_memory_dir()` now resolves from `get_mente_home() / "memories"`.
  - This prevents curated memory from preferring an old `HERMES_HOME` when `MENTE_HOME` is the intended runtime root.

### Standalone / helper paths

- `tools/mcp_oauth.py`
  - import-fallback path resolution now checks `HERMES_HOME`, then `MENTE_HOME`, then defaults to `~/.mente`.
- `agent/file_safety.py`
  - fallback runtime-home resolution now checks `MENTE_HOME` and defaults to `~/.mente`.
- `skills/productivity/google-workspace/scripts/_hermes_home.py`
  - standalone helper fallback now checks `HERMES_HOME`, then `MENTE_HOME`, then defaults to `~/.mente`.
- `optional-skills/productivity/memento-flashcards/scripts/memento_cards.py`
  - standalone storage root now checks `HERMES_HOME`, then `MENTE_HOME`, then defaults to `~/.mente`.
- `optional-skills/productivity/telephony/scripts/telephony.py`
  - standalone storage root now checks `HERMES_HOME`, then `MENTE_HOME`, then defaults to `~/.mente`.
- `scripts/discord-voice-doctor.py`
  - standalone env/config lookup now checks `HERMES_HOME`, then `MENTE_HOME`, then defaults to `~/.mente`.
- `scripts/build_skills_index.py`
  - bootstrap import guard now seeds `HERMES_HOME` from `MENTE_HOME` or `~/.mente`, never `~/.hermes`.
- `scripts/build_model_catalog.py`
  - bootstrap import guard now seeds `HERMES_HOME` from `MENTE_HOME` or `~/.mente`, never `~/.hermes`.
- `scripts/profile-tui.py`
  - standalone perf/state defaults now resolve from `HERMES_HOME`, then `MENTE_HOME`, then `~/.mente`.
- `scripts/lib/node-bootstrap.sh`
  - bundled Node install root now resolves from `HERMES_HOME`, then `MENTE_HOME`, then `~/.mente`.
- `scripts/whatsapp-bridge/bridge.js`
  - standalone session/cache roots now resolve from `HERMES_HOME`, then `MENTE_HOME`, then `~/.mente`.
- `skills/github/github-auth/scripts/gh-env.sh`
  - skill helper now checks `${HERMES_HOME:-${MENTE_HOME:-$HOME/.mente}}/.env` instead of hardcoded `~/.hermes/.env`.
- `scripts/hermes-gateway`
  - standalone launchd log paths now resolve from `HERMES_HOME`, then `MENTE_HOME`, then `~/.mente`.
- `optional-skills/migration/openclaw-migration/scripts/openclaw_to_hermes.py`
  - default `--target` now resolves from `HERMES_HOME`, then `MENTE_HOME`, then `~/.mente`, and user-facing destination display no longer hardcodes `~/.hermes`.
- `optional-skills/migration/openclaw-migration/SKILL.md`
  - migration helper examples now reference the active agent root instead of hardcoded `~/.hermes`.
- `skills/red-teaming/godmode/SKILL.md`
  - execute_code examples and persistence paths now reference `MENTE_HOME` / `~/.mente` semantics.
- `skills/red-teaming/godmode/references/refusal-detection.md`
  - example loader path now references `MENTE_HOME` / `~/.mente`.
- `skills/red-teaming/godmode/references/jailbreak-templates.md`
  - config and example loader paths now reference the active agent root instead of `~/.hermes`.
- `skills/productivity/google-workspace/SKILL.md`
  - helper aliases and OAuth storage paths now reference `${HERMES_HOME:-${MENTE_HOME:-$HOME/.mente}}`.
- `skills/github/github-auth/SKILL.md`
  - fallback token-loading example now references `${HERMES_HOME:-${MENTE_HOME:-$HOME/.mente}}/.env`.

### Profiles

- `hermes_cli/profiles.py`
  - profile root inheritance now follows the updated `get_default_hermes_root()` behavior, so unbootstrapped profile operations default to `~/.mente/profiles`.

## Direct `~/.hermes` Doc/Shell Bypasses

The previously identified doc/shell batch that still advertised legacy invocation roots has now been cleared:

- Cleared in this pass:
  - `optional-skills/creative/touchdesigner-mcp/SKILL.md`
  - `skills/github/github-repo-management/references/github-api-cheatsheet.md`
  - `skills/github/github-pr-workflow/SKILL.md`
  - `skills/github/github-code-review/SKILL.md`
  - `skills/github/github-issues/SKILL.md`
  - `optional-skills/productivity/memento-flashcards/SKILL.md`
  - `optional-skills/productivity/telephony/SKILL.md`
- Those examples now point at the active agent root via `HERMES_HOME -> MENTE_HOME -> ~/.mente`.

## Bootstrap-Dependent Legacy Semantics Still Present

These are not immediate `~/.hermes` fallbacks after this pass, but they still depend on legacy Hermes-named helpers or storage semantics and should be migrated in later rounds:

### Memory stack

- `agent/memory_manager.py`
- `plugins/memory/byterover/__init__.py`
- `plugins/memory/hindsight/__init__.py`
- `plugins/memory/holographic/__init__.py`
- `plugins/memory/holographic/store.py`
- `plugins/memory/honcho/__init__.py`
- `plugins/memory/honcho/cli.py`
- `plugins/memory/honcho/client.py`
- `plugins/memory/honcho/session.py`
- `plugins/memory/mem0/__init__.py`
- `plugins/memory/retaindb/__init__.py`
- `plugins/memory/supermemory/__init__.py`

### Skills/runtime helpers

- `tools/skills_tool.py`
- `tools/skills_sync.py`
- `agent/skill_utils.py`
- `agent/skill_commands.py`
- `skills/productivity/google-workspace/scripts/google_api.py`
- `skills/productivity/google-workspace/scripts/gws_bridge.py`
- `skills/productivity/google-workspace/scripts/setup.py`

These are currently safe when launched through Mente entrypoints because bootstrap bridges `HERMES_HOME` to `MENTE_HOME`, but they still carry Hermes-era naming or helper dependencies internally.

## Regression Coverage Added / Reconfirmed

### Main entrypoints

- `tests/mente/test_runtime_home.py`
- `tests/hermes_cli/test_mente_oneshot.py`
- `tests/tui_gateway/test_protocol.py`
- `tests/hermes_cli/test_mente_runtime_bootstrap.py`

### Memory / profile / standalone skills

- `tests/tools/test_memory_tool.py`
- `tests/tools/test_mcp_oauth.py`
- `tests/test_hermes_constants.py`
- `tests/hermes_cli/test_profiles.py`
- `tests/skills/test_google_oauth_setup.py`
- `tests/skills/test_memento_cards.py`
- `tests/skills/test_telephony_skill.py`
- `tests/skills/test_godmode_home_resolution.py`
- `tests/skills/test_touchdesigner_setup.py`
- `tests/test_standalone_script_home_resolution.py`
