---
title: "Mente Config Admin — Use when the user asks Mente to change API keys, OAuth/provider auth, config"
sidebar_label: "Mente Config Admin"
description: "Use when the user asks Mente to change API keys, OAuth/provider auth, config"
---

{/* This page is auto-generated from the skill's SKILL.md by website/scripts/generate-skill-docs.py. Edit the source SKILL.md, not this page. */}

# Mente Config Admin

Use when the user asks Mente to change API keys, OAuth/provider auth, config.yaml or .env settings, gateway/platform credentials, or restart/reload services after configuration changes.

## Skill metadata

| | |
|---|---|
| Source | Bundled (installed by default) |
| Path | `skills/software-development/mente-config-admin` |
| Version | `1.0.0` |
| Author | Mente |
| License | MIT |
| Tags | `mente`, `config`, `api-key`, `oauth`, `auth`, `gateway`, `env`, `config-yaml`, `operations` |
| Related skills | [`hermes-agent`](/user-guide/skills/bundled/autonomous-ai-agents/autonomous-ai-agents-hermes-agent), [`systematic-debugging`](/user-guide/skills/bundled/software-development/software-development-systematic-debugging), `verification-before-completion` |

## Reference: full SKILL.md

:::info
The following is the complete skill definition that Hermes loads when this skill is triggered. This is what the agent sees as instructions when the skill is active.
:::

# Mente Config Admin

## Overview

Use this skill for user-facing operational changes to Mente itself: changing API keys, rotating provider credentials, updating `config.yaml`, fixing gateway platform tokens, or restarting the gateway after a config change.

This is not a general coding skill. It is an operational playbook for safely modifying live Mente configuration without breaking the current install, profile, or executor auth flow.

## When to Use

- The user says things like:
  - "帮我改 API key"
  - "把 OpenRouter key 换掉"
  - "改一下模型配置"
  - "重登 Codex"
  - "修改 Feishu/Slack/微信 token"
  - "改 gateway 配置"
  - "改 `.env` / `config.yaml`"
  - "改 Mente 的登录态"
- The task touches provider auth, gateway auth, model provider selection, platform secrets, or restart behavior.
- The user wants Mente to perform the change directly instead of just explaining it.

Do not use this skill for ordinary application code changes inside a user project.

## Core Rule

Always classify the request first. These targets are different:

| Target | Canonical storage | Normal action |
|---|---|---|
| API keys / tokens / secrets | effective `HERMES_HOME/.env` | Edit `.env` |
| Non-secret settings | effective `HERMES_HOME/config.yaml` | Edit `config.yaml` |
| OAuth / device-code auth state | effective `HERMES_HOME/auth.json` | Prefer `mente model`, `mente auth`, `mente logout`; do not hand-edit unless forced |
| Skills / skill state | `MENTE_HOME/skills/` | Not part of ordinary key rotation |

Two names exist in the codebase:

- `get_hermes_home()` is still the effective runtime home for config, auth, gateway state, logs, and `.env`.
- `get_mente_home()` is the separate Mente-owned home used for skills and some executor-specific assets.

Do not guess which root is active. Resolve the real paths first.

## Resolve Paths First

Before editing anything, resolve the active config files from the running install:

```bash
mente config path
mente config env-path
```

If you need to inspect the effective homes directly:

```bash
python - <<'PY'
from hermes_constants import get_hermes_home, get_mente_home, display_hermes_home, display_mente_home
print("effective_config_home =", get_hermes_home())
print("display_config_home   =", display_hermes_home())
print("effective_skills_home =", get_mente_home())
print("display_skills_home   =", display_mente_home())
PY
```

Rules:

1. Edit the path returned by the commands, not a hardcoded `~/.hermes` or `~/.mente`.
2. Read the existing file before changing it.
3. Patch only the targeted keys. Preserve comments, ordering, and unrelated settings.

## Secret vs Non-Secret

### Use `.env` for secrets

Examples:

- `OPENROUTER_API_KEY`
- `OPENAI_API_KEY`
- provider API keys from `hermes_cli/auth.py` `api_key_env_vars`
- messaging / platform tokens stored as env vars

Procedure:

1. Resolve the active `.env` path with `mente config env-path`.
2. Read the current file.
3. Replace the existing key in place, or append it if missing.
4. Do not echo the full secret back to the user. Redact it.

Do not move secrets into `config.yaml`.

### Use `config.yaml` for non-secret settings

Examples:

- `model.provider`
- `model.default`
- `model.base_url`
- display flags
- gateway feature toggles
- title generation settings
- `terminal.cwd`

Procedure:

1. Resolve the active config path with `mente config path`.
2. Read the current YAML.
3. Change only the requested keys.
4. Keep the YAML structure intact; do not flatten or rewrite unrelated sections.

Do not store plain API keys in `config.yaml` unless the code explicitly requires that format.

## Provider/Auth Decision Tree

### Case 1: Standard API-key provider

Examples: OpenRouter, OpenAI-compatible direct keys, Anthropic API keys, Gemini API keys, Z.AI, Kimi, StepFun, MiniMax.

Action:

- Update the correct env var in `.env`.
- If the user is also switching providers, update `config.yaml` `model.provider` and related model fields.
- Restart the gateway after the change if requests come through the gateway.

How to find the correct env var:

- Check `hermes_cli/auth.py` `PROVIDER_REGISTRY[provider].api_key_env_vars`.
- Use the first canonical env var unless the repo already uses a different one for that install.

### Case 2: OAuth / device-code provider

Examples: `openai-codex`, `nous`, `qwen-oauth`, `google-gemini-cli`, Anthropic OAuth.

Action:

- Prefer supported auth flows over manual file editing.
- Use `mente model`, `mente auth`, or `mente logout` depending on the task.
- Do not manually patch `auth.json` unless the user explicitly asks for a surgical recovery and you have already backed it up.

### Case 3: Internal Codex executor auth

This case is special.

Mente's internal Codex executor reads runtime credentials from `resolve_codex_runtime_credentials()` in `hermes_cli.auth`, backed by provider state inside `auth.json`.

Preferred procedure:

1. If the user wants to replace the internal Codex login, clear the old session with:
   ```bash
   mente logout openai-codex
   ```
2. Re-run provider setup through:
   ```bash
   mente model
   ```
3. Choose `OpenAI Codex` in the model flow and complete the device/browser auth.
4. Verify that `model.provider` is `openai-codex` and the auth state is usable.

Important:

- Do not recommend `mente login`; that flow has been removed.
- Do not treat internal Codex auth as a simple `.env` key replacement.
- Prefer `mente model` over ad-hoc `auth.json` edits for normal maintenance.

## File Editing Rules

### `.env`

- Replace only the target variable.
- If the user says "remove" or "clear", blank or delete only that variable.
- Preserve neighboring comments and unrelated keys.
- Never print the full value in your reply.

### `config.yaml`

- Change only the requested subtree.
- Preserve existing dict structure.
- If a provider switch would leave a stale, conflicting field, remove only that conflicting field.

### `auth.json`

- Treat as sensitive state.
- Read-only by default.
- If manual repair is unavoidable, make a backup first and modify the smallest possible fragment.
- Never expose tokens in the response.

## Gateway Restart Rules

Restart the gateway when any of the following changed:

- `.env`
- provider auth / OAuth state
- platform adapter tokens or secrets
- gateway-specific configuration that is only read on process start

Usually use:

```bash
mente gateway restart
```

For simple `config.yaml` changes that are re-read on the next request, a restart may not always be mandatory, but it is still the safe default for messaging/gateway flows. When in doubt, restart and tell the user you did it.

## User-Facing Response Rules

- Say exactly what was changed: file, key, and whether the gateway was restarted.
- Redact secrets: show only a short prefix/suffix if confirmation is needed.
- If a browser or device-code step is required, say so explicitly.
- If you could not finish because an interactive login is required, stop at that boundary and explain the next step precisely.

## One-Shot Recipes

### Rotate a normal API key

1. Resolve `.env` path with `mente config env-path`.
2. Read the file.
3. Replace the target env var in place.
4. Restart gateway with `mente gateway restart`.
5. Confirm the key was updated without printing the full value.

### Change a non-secret config value

1. Resolve config path with `mente config path`.
2. Read `config.yaml`.
3. Patch only the requested key.
4. Restart the gateway if the user is using Mente through messaging.

### Re-link internal Codex executor auth

1. `mente logout openai-codex`
2. `mente model`
3. Select `OpenAI Codex`
4. Complete device/browser auth
5. Restart gateway if requests flow through the gateway

## Common Pitfalls

1. Editing `~/.hermes` or `~/.mente` by assumption instead of resolving the active path first.
2. Writing secrets into `config.yaml` when they belong in `.env`.
3. Using `mente login` for Codex auth even though that flow is removed.
4. Hand-editing `auth.json` for ordinary OAuth maintenance.
5. Rewriting the whole `.env` or YAML file and destroying unrelated user settings.
6. Forgetting the gateway restart after changing secrets or auth state.
7. Echoing the user's full API key back into chat or logs.

## Verification Checklist

- [ ] Resolved the active config and env paths before editing
- [ ] Read the current file before patching
- [ ] Changed only the intended key(s)
- [ ] Kept secrets out of the response
- [ ] Restarted the gateway when the change affected runtime auth or env
- [ ] Verified the resulting file or command output reflects the requested change
