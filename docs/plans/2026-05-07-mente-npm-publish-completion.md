# Mente NPM Publish Completion Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Finish the npm publish chain so `mente-agent` can be safely released from GitHub with version/tag validation and a minimal release runbook.

**Architecture:** Keep npm publication tag-driven for auditability, add a small Node preflight validator shared by tests and the GitHub workflow, and document the shortest human path: set `NPM_TOKEN`, run workflow preflight, push `npm-v<package-version>` tag. This avoids accidental workflow-dispatch publication while preserving a fast dry-run path.

**Tech Stack:** GitHub Actions, Node test runner, package.json metadata, small CommonJS helper, markdown release docs.

---

### Task 1: Add a failing test for npm release validation

**Files:**
- Modify: `tests/npm-installer/mente-installer.test.mjs`
- Create: `npm/installer/lib/publish-check.cjs`

**Steps:**
1. Add a test that expects a helper to compute `npm-v<version>` from `package.json`.
2. Add a test that expects tag validation to fail when the pushed tag does not match the package version.
3. Run `npm run test:npm-installer` and verify failure.

### Task 2: Implement the publish preflight helper

**Files:**
- Create: `npm/installer/lib/publish-check.cjs`
- Create: `scripts/validate-npm-publish.cjs`
- Modify: `package.json`

**Steps:**
1. Implement helper functions for expected tag derivation and publish-context validation.
2. Add a small CLI wrapper script so GitHub Actions can run the same validation logic.
3. Add a package script like `release:check:npm` for local/manual preflight.
4. Run the Node tests again and make them pass.

### Task 3: Harden the workflow into preflight + publish

**Files:**
- Modify: `.github/workflows/npm-publish.yml`

**Steps:**
1. Change `workflow_dispatch` into preflight-only behavior.
2. Keep real publication only on `push.tags = npm-v*`.
3. Add explicit validation that tag matches `package.json` version.
4. Add a duplicate-version guard with `npm view mente-agent@<version>` so the workflow fails clearly if that version is already published.
5. Verify the workflow YAML and logic by inspection and local script invocation.

### Task 4: Add the shortest release runbook

**Files:**
- Create: `docs/releasing/npm.md`
- Modify: `README.md`
- Modify: `README.zh.md`

**Steps:**
1. Document the exact prerequisites: npm owner access and GitHub `NPM_TOKEN` secret.
2. Document the shortest happy-path release sequence with exact commands.
3. Link the runbook from the README npm install section.
4. Keep it short enough for operators to follow without interpretation.

### Task 5: Verify and ship

**Files:**
- Modify: all files above as needed

**Steps:**
1. Run `npm run test:npm-installer`.
2. Run `npm run release:check:npm` locally in preflight mode.
3. Run `npm pack --dry-run`.
4. Run targeted repo tests if project metadata changes.
5. Commit and push to `main`.
