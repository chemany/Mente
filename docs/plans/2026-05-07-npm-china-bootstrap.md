# NPM China Bootstrap Implementation Plan

> **For Mente:** Use `executing-plans` to implement this plan task-by-task.

**Goal:** Add a `--china` install mode and reduce GitHub dependency by letting the npm bootstrapper install from a bundled local runtime source when available.

**Architecture:** The npm package will generate and publish a tracked-source runtime bundle during `prepack`, then the bootstrap launcher will pass that bundle into the shell or PowerShell installer. The installers will gain a local-bundle install path plus a `--china` mode that rewires download endpoints and skips eager network-heavy steps unless explicitly requested.

**Tech Stack:** Node.js, Python stdlib (`tarfile`), bash, PowerShell, existing npm installer tests, existing Python installer metadata tests.

---

### Task 1: Lock the expected install surface with tests

**Files:**
- Modify: `tests/npm-installer/mente-installer.test.mjs`
- Modify: `tests/test_install_metadata.py`

**Step 1: Write the failing test**

Add expectations for:
- npm bootstrap args including `--china`
- npm bootstrap args including `--source-tarball <bundled path>`
- package metadata including `prepack` and bundled runtime source publish entries
- shell / PowerShell installer help and messages including `--china` and `--source-tarball`

**Step 2: Run test to verify it fails**

Run: `npm run test:npm-installer`
Expected: FAIL on missing helper export / missing bundled source arg support

Run: `scripts/run_tests.sh tests/test_install_metadata.py`
Expected: FAIL on missing installer option text

### Task 2: Build and publish a local runtime source bundle from npm

**Files:**
- Modify: `package.json`
- Create: `scripts/build_npm_source_bundle.py`
- Modify: `npm/installer/lib/paths.cjs`

**Step 1: Write minimal implementation**

Add a `prepack` script that builds `npm/installer/bundles/mente-runtime-source.tar.gz` from tracked working-tree files. Expose helper(s) from `paths.cjs` so the bootstrapper can locate the bundle and add `--source-tarball` when it exists.

**Step 2: Run targeted tests**

Run: `npm run test:npm-installer`
Expected: PASS

### Task 3: Teach bootstrap installers to use the local bundle first

**Files:**
- Modify: `npm/installer/bin/mente.cjs`
- Modify: `scripts/install.sh`
- Modify: `scripts/install.ps1`

**Step 1: Write minimal implementation**

Add installer flags:
- shell: `--china`, `--source-tarball`
- PowerShell: `-China`, `-SourceTarball`

Implement a safe local-source install path:
- fresh install without `.git` uses the local bundle when provided
- bundle-managed installs can refresh in place
- git working trees remain on the git update path

**Step 2: Run targeted tests**

Run: `npm run test:npm-installer`
Expected: PASS

Run: `scripts/run_tests.sh tests/test_install_metadata.py`
Expected: PASS

### Task 4: Add China-specific network defaults

**Files:**
- Modify: `scripts/install.sh`
- Modify: `scripts/install.ps1`

**Step 1: Write minimal implementation**

In `--china` mode:
- prefer local/npm bundle over git
- set Python / npm / Playwright mirror env vars
- switch Node and GitHub archive base URLs to configurable mirror-friendly defaults
- keep explicit env overrides for every endpoint

**Step 2: Run verification**

Run: `npm run test:npm-installer`
Expected: PASS

Run: `scripts/run_tests.sh tests/test_install_metadata.py`
Expected: PASS

Run: `npm pack --dry-run`
Expected: bundled runtime source tarball included in publish output

### Task 5: Final verification

**Files:**
- Modify only files touched above

**Step 1: Run full verification for this change set**

Run:
- `npm run test:npm-installer`
- `scripts/run_tests.sh tests/test_install_metadata.py`
- `npm pack --dry-run`

**Step 2: Commit**

```bash
git add package.json scripts/build_npm_source_bundle.py npm/installer/bin/mente.cjs npm/installer/lib/paths.cjs scripts/install.sh scripts/install.ps1 tests/npm-installer/mente-installer.test.mjs tests/test_install_metadata.py docs/plans/2026-05-07-npm-china-bootstrap.md
git commit -m "feat: add china-aware npm bootstrap path"
```
