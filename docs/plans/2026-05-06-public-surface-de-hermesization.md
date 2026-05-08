# Public Surface De-Hermesization Implementation Plan

> **For Mente:** Use `executing-plans` to implement this plan task-by-task.

**Goal:** Remove remaining public-facing Hermes / NousResearch branding from the repo surface and replace it with Mente-branded descriptions, titles, and links.

**Architecture:** Limit this pass to user-visible surfaces: GitHub-facing docs and templates, website branding and outbound links, and runtime strings shown directly to users in ACP, CLI, TUI, or web UI. Leave internal module names, compatibility comments, and historical references untouched unless they are displayed to end users.

**Tech Stack:** Markdown docs, Docusaurus website files, Python runtime strings, TypeScript TUI theme, GitHub metadata templates.

---

### Task 1: Normalize repo-facing copy and links

**Files:**
- Modify: `README.md`
- Modify: `.github/PULL_REQUEST_TEMPLATE.md`
- Modify: `.github/ISSUE_TEMPLATE/*.yml`

**Steps:**
1. Replace old Hermes/NousResearch repo links with `chemany/Mente`.
2. Remove stale public docs/homepage references that still point at NousResearch Hermes properties.
3. Keep contributor/process wording intact unless the agent name itself is user-facing.

### Task 2: Normalize public site branding

**Files:**
- Modify: `website/**`
- Modify: `website/static/api/model-catalog.json`
- Modify: `website/scripts/generate-skill-docs.py`

**Steps:**
1. Replace user-facing “Hermes Agent” product naming with “Mente”.
2. Replace old docs/repo URLs with Mente repo URLs.
3. Keep generated/reference-heavy content out of scope unless it is part of the main user-facing site shell or high-traffic getting-started pages.

### Task 3: Normalize runtime-displayed labels

**Files:**
- Modify: `acp_adapter/server.py`
- Modify: `ui-tui/src/theme.ts`
- Modify: `ui-tui/src/__tests__/theme.test.ts`
- Modify: `hermes_cli/web_dist/index.html`

**Steps:**
1. Replace user-visible runtime labels such as “Hermes Agent” titles/version strings with “Mente”.
2. Keep package/module identifiers unchanged unless the user directly sees them.
3. Add or adjust tests only where existing coverage already asserts branding output.

### Task 4: Verify targeted sweep

**Files:**
- Inspect only

**Steps:**
1. Run focused searches over the edited public-surface files.
2. Run the minimal tests that cover edited runtime strings.
3. Report remaining Hermes residues that are intentionally out of scope for this pass.
