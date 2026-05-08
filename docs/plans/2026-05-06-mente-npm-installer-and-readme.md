# Mente NPM Installer And README Implementation Plan

> **For Mente:** Use `executing-plans` to implement this plan task-by-task.

**Goal:** Publishable `mente-agent` NPM installer package plus updated README with one-command install and packaging safety guarantees.

**Architecture:** Keep the Python/runtime distribution path as-is. Add a thin Node global wrapper that ships a safe subset of files, bootstraps the existing install script on first run, then hands off to the real `mente` binary. Protect npm publish with an explicit `files` allowlist so secrets and local state cannot enter the tarball.

**Tech Stack:** npm package metadata, Node CLI wrapper, existing shell installer, markdown README, node:test verification.

---

### Task 1: Add failing tests for installer resolution and package safety

**Files:**
- Create: `tests/npm-installer/mente-installer.test.mjs`
- Modify: `package.json`

**Steps:**
1. Write a failing Node test that expects a reusable installer helper module to resolve the packaged install script and detect existing binaries.
2. Write a failing Node test that expects package metadata to include a publishable `name`, `bin`, and restrictive `files` allowlist.
3. Add a test script to `package.json` for the new Node test target.
4. Run the Node tests to confirm they fail for the expected reasons.

### Task 2: Implement the installer wrapper package

**Files:**
- Create: `npm/installer/lib/paths.cjs`
- Create: `npm/installer/bin/mente.cjs`
- Modify: `package.json`

**Steps:**
1. Implement a helper module that resolves the package root, bundled install script, and common installed `mente` binary locations.
2. Implement a CLI wrapper that:
   - executes an existing installed `mente` binary when present;
   - otherwise runs bundled `scripts/install.sh` pinned to the package version;
   - re-execs `mente` after successful bootstrap.
3. Update `package.json` from private internal metadata to a publishable `mente-agent` package with `bin`, `files`, and safe publish metadata.
4. Re-run the Node tests until green.

### Task 3: Harden package contents against secret leakage

**Files:**
- Modify: `package.json`
- Inspect: `.gitignore`, `MANIFEST.in`, `scripts/install.sh`

**Steps:**
1. Keep npm package contents whitelist-only via `files`.
2. Include only the minimum required publish surface: wrapper bin, helper library, installer scripts, README, LICENSE.
3. Verify that `.env`, auth state, local homes, worktrees, and runtime caches are excluded by construction.
4. Run `npm pack --dry-run` and inspect the file list.

### Task 4: Update README for combined product + release positioning

**Files:**
- Modify: `README.md`
- Create/Modify: `assets/...` for package/readme visuals if needed

**Steps:**
1. Update install instructions so npm is the first-path entry point.
2. Summarize the recent Mente-facing changes: external branding consolidation, internal Codex executor retained, restored progress visibility, config/admin workflow skill, gateway de-Hermes work.
3. Add a packaging safety note explaining that npm install does not publish user secrets.
4. Add or refresh visuals referenced by the README.

### Task 5: Verify, commit, and prepare push

**Files:**
- Modify: relevant changed files from tasks above

**Steps:**
1. Run the Node test target.
2. Run `npm pack --dry-run` and verify output.
3. Run targeted repo tests only if touched Python integration behavior needs coverage.
4. Review diff for only intended files.
5. Commit the installer + README changes.
6. Attempt push to `main` if repository/auth state permits; otherwise report the exact blocker.
