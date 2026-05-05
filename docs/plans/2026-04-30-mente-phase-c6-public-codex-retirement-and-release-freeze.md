# Phase C6: Public Codex Retirement And Release Freeze Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Retire the ambient public `codex` binary from Mente’s release/main path and make every Mente release carry an explicit, frozen vendored Codex runtime + upgrade/install contract.

**Architecture:** C4 switched the execution control plane to the vendored bridge and C5 froze the vendored capability surface, but the current bridge still points at a source-tree runtime path that is not actually present in the vendored snapshot, while the current install/update path is still branch-oriented (`main`) instead of release-frozen. C6 should introduce a Mente-owned release-freeze contract that binds together: (1) the upstream Codex snapshot id, (2) the allowed Mente patch set, (3) the vendored capability manifest, (4) the platform-specific vendored runtime artifacts, and (5) the one-click install / update / rollback policy. The main runtime resolver must load only that frozen contract, installers must bootstrap a matching vendored runtime artifact, and upgrades must happen by Mente release identifier rather than ambient public `codex` or moving branch head. `CodexKernelAdapter` remains the only upper-layer seam; Mente continues to own runtime/policy/orchestration outside vendored upstream.

**Tech Stack:** Python, shell install scripts, PowerShell, setuptools packaging, GitHub release artifacts, pytest, compileall, vendored Codex upstream staging scripts

---

### Task 1: Freeze The C6 Baseline And Make The Gaps Executable

**Files:**
- Create: `docs/plans/2026-04-30-mente-codex-release-freeze-manifest.md`
- Create: `tests/mente/test_codex_release_freeze.py`
- Modify: `tests/mente/test_codex_bridge.py`
- Modify: `tests/test_project_metadata.py`
- Reference: `kernel/codex/bridge/entrypoints.py`
- Reference: `kernel/codex/upstream/sdk/python-runtime/README.md`
- Reference: `kernel/codex/upstream/sdk/python/scripts/update_sdk_artifacts.py`
- Reference: `pyproject.toml`
- Reference: `MANIFEST.in`

**Step 1: Write the failing test**

Add coverage that asserts all C6 preconditions explicitly:
- the main path must not rely on ambient public `codex` discovery
- the bridge’s vendored runtime path must be backed by a real release-freeze contract rather than a bare source-tree assumption
- packaging metadata for release installs must include the `kernel/codex/` slice
- a C6 release-freeze manifest must exist and record the current snapshot/capability boundary inputs

**Step 2: Run test to verify it fails**

Run:

```bash
scripts/run_tests.sh tests/mente/test_codex_release_freeze.py tests/mente/test_codex_bridge.py tests/test_project_metadata.py -v
```

Expected:
- FAIL because the C6 release-freeze manifest does not exist yet
- FAIL because packaging metadata does not yet include the vendored kernel slice
- FAIL because the bridge still treats a source-tree runtime path as the selected front door

**Step 3: Write minimal implementation**

Create a documentation-first manifest that records the current C6 starting state:
- pinned upstream snapshot id from C3
- C4 bridge cutover status
- C5 capability-surface status
- current runtime-resolution gap
- current packaging/install gap

Do not change runtime behavior yet.

**Step 4: Run test to verify it passes**

Run:

```bash
scripts/run_tests.sh tests/mente/test_codex_release_freeze.py tests/mente/test_codex_bridge.py tests/test_project_metadata.py -v
```

Expected:
- PASS for the new baseline assertions

**Step 5: Commit**

```bash
git add docs/plans/2026-04-30-mente-codex-release-freeze-manifest.md tests/mente/test_codex_release_freeze.py tests/mente/test_codex_bridge.py tests/test_project_metadata.py
git commit -m "docs: record c6 codex release freeze baseline"
```

### Task 2: Replace The Source-Tree Runtime Assumption With A Frozen Vendored Runtime Locator

**Files:**
- Create: `kernel/codex/release/__init__.py`
- Create: `kernel/codex/release/manifest.py`
- Create: `kernel/codex/release/runtime.py`
- Modify: `kernel/codex/bridge/entrypoints.py`
- Modify: `kernel/codex/runtime/runner.py`
- Modify: `mente/executors/codex.py`
- Modify: `tests/mente/test_codex_bridge.py`
- Modify: `tests/mente/test_codex_executor.py`
- Modify: `tests/mente/test_kernel_runner.py`
- Reference: `kernel/codex/upstream/sdk/python-runtime/src/codex_cli_bin/__init__.py`
- Reference: `kernel/codex/upstream/sdk/python/README.md`

**Step 1: Write the failing test**

Extend coverage so it asserts:
- bridge/runtime resolution comes from a Mente-owned frozen runtime manifest
- missing vendored runtime bootstrap fails closed with an explicit, actionable error
- the production resolver no longer assumes `kernel/codex/upstream/sdk/python-runtime/src/codex_cli_bin/bin/codex` exists in the source tree
- no production path falls back to ambient `codex` on `PATH`

**Step 2: Run test to verify it fails**

Run:

```bash
scripts/run_tests.sh tests/mente/test_codex_bridge.py tests/mente/test_codex_executor.py tests/mente/test_kernel_runner.py tests/mente/test_codex_release_freeze.py -v
```

Expected:
- FAIL because the bridge still points at a source-tree binary path and has no frozen runtime manifest loader

**Step 3: Write minimal implementation**

Introduce a kernel-owned release/runtime contract that:
- resolves the vendored runtime from a release manifest produced by Mente
- allows an explicit break-glass vendored-runtime override for testing/rollback only
- returns a deterministic `runtime_not_bootstrapped`/equivalent failure when the frozen runtime artifact is absent
- keeps `CodexKernelAdapter` unchanged

Do **not** reintroduce public `codex` fallback. Do **not** move auth/product logic into `kernel/codex/upstream/`.

**Step 4: Run test to verify it passes**

Run:

```bash
scripts/run_tests.sh tests/mente/test_codex_bridge.py tests/mente/test_codex_executor.py tests/mente/test_kernel_runner.py tests/mente/test_codex_release_freeze.py -v
```

Expected:
- PASS

**Step 5: Commit**

```bash
git add kernel/codex/release/__init__.py kernel/codex/release/manifest.py kernel/codex/release/runtime.py kernel/codex/bridge/entrypoints.py kernel/codex/runtime/runner.py mente/executors/codex.py tests/mente/test_codex_bridge.py tests/mente/test_codex_executor.py tests/mente/test_kernel_runner.py
git commit -m "feat: resolve vendored codex runtime from frozen release manifest"
```

### Task 3: Package The Vendored Kernel Slice In Mente Release Artifacts

**Files:**
- Create: `kernel/__init__.py`
- Modify: `pyproject.toml`
- Modify: `MANIFEST.in`
- Create: `tests/mente/test_release_packaging.py`
- Modify: `tests/test_project_metadata.py`
- Reference: `kernel/codex/__init__.py`
- Reference: `kernel/codex/upstream/README.mente.md`

**Step 1: Write the failing test**

Add packaging-focused tests that assert:
- the built Mente sdist/wheel contains `kernel/codex/bridge/`, `kernel/codex/runtime/`, `kernel/codex/session/`, `kernel/codex/sandbox/`, and the release-freeze metadata
- the distribution is importable without relying on an editable checkout
- packaging does not silently exclude the vendored kernel slice

**Step 2: Run test to verify it fails**

Run:

```bash
scripts/run_tests.sh tests/mente/test_release_packaging.py tests/test_project_metadata.py -v
uv run python -m build
```

Expected:
- FAIL because current setuptools metadata excludes `kernel*`
- build output is missing the vendored kernel slice and/or release-freeze metadata

**Step 3: Write minimal implementation**

Update packaging metadata so release artifacts include the vendored kernel slice and its manifests.

Keep the ownership boundary intact:
- vendored Codex source remains vendored source
- bridge/runtime/release metadata remain Mente-owned
- no product logic moves into `kernel/codex/upstream/`

**Step 4: Run test to verify it passes**

Run:

```bash
scripts/run_tests.sh tests/mente/test_release_packaging.py tests/test_project_metadata.py -v
uv run python -m build
uv run python -m compileall kernel/codex mente hermes_cli
```

Expected:
- tests PASS
- build succeeds
- `compileall` exit code `0`

**Step 5: Commit**

```bash
git add kernel/__init__.py pyproject.toml MANIFEST.in tests/mente/test_release_packaging.py tests/test_project_metadata.py
git commit -m "build: package vendored codex kernel slice in mente releases"
```

### Task 4: Teach The Release Pipeline To Produce Frozen Vendored Runtime Artifacts

**Files:**
- Create: `scripts/build_mente_codex_runtime_artifacts.py`
- Modify: `scripts/release.py`
- Modify: `docs/plans/2026-04-30-mente-codex-release-freeze-manifest.md`
- Modify: `kernel/codex/upstream/README.mente.md`
- Modify: `tests/mente/test_release_packaging.py`
- Reference: `kernel/codex/upstream/sdk/python/scripts/update_sdk_artifacts.py`
- Reference: `kernel/codex/upstream/sdk/python-runtime/pyproject.toml`
- Reference: `packaging/homebrew/README.md`

**Step 1: Write the failing test**

Add tests that assert the release flow can produce, or at minimum fully describe, a frozen vendored runtime artifact set per Mente release:
- one release-freeze manifest entry per supported platform artifact
- exact version pinning back to the vendored snapshot/release id
- artifact digest(s) available for installer verification
- artifact production reuses vendored upstream staging helpers instead of reimplementing runtime packaging logic from scratch

**Step 2: Run test to verify it fails**

Run:

```bash
scripts/run_tests.sh tests/mente/test_release_packaging.py tests/mente/test_codex_release_freeze.py -v
uv run python scripts/release.py --help
```

Expected:
- FAIL because the release flow does not yet produce vendored runtime artifacts or a freeze manifest that installers can consume

**Step 3: Write minimal implementation**

Build a thin Mente-owned wrapper around the vendored upstream staging flow:
- reuse `kernel/codex/upstream/sdk/python/scripts/update_sdk_artifacts.py`
- produce a Mente-consumable runtime artifact contract per release
- record artifact filename, platform tag, version, and sha256 in the C6 release-freeze manifest
- keep binaries out of the git repo

Prefer installer-consumable runtime wheels/artifacts derived from the vendored upstream runtime package rather than inventing a second capability/runtime implementation.

**Step 4: Run test to verify it passes**

Run:

```bash
scripts/run_tests.sh tests/mente/test_release_packaging.py tests/mente/test_codex_release_freeze.py -v
uv run python scripts/build_mente_codex_runtime_artifacts.py --help
uv run python scripts/release.py --help
```

Expected:
- tests PASS
- both scripts exit `0`

**Step 5: Commit**

```bash
git add scripts/build_mente_codex_runtime_artifacts.py scripts/release.py docs/plans/2026-04-30-mente-codex-release-freeze-manifest.md kernel/codex/upstream/README.mente.md tests/mente/test_release_packaging.py tests/mente/test_codex_release_freeze.py
git commit -m "build: freeze vendored codex runtime artifacts per mente release"
```

### Task 5: Switch Install, Bootstrap, And Update Flows To Release-Pinned Artifacts

**Files:**
- Modify: `scripts/install.sh`
- Modify: `scripts/install.ps1`
- Modify: `setup-hermes.sh`
- Modify: `README.md`
- Modify: `hermes_cli/main.py`
- Modify: `hermes_cli/config.py`
- Create: `tests/hermes_cli/test_mente_runtime_bootstrap.py`
- Reference: `packaging/homebrew/README.md`
- Reference: `packaging/homebrew/hermes-agent.rb`

**Step 1: Write the failing test**

Add coverage that asserts:
- one-click install defaults to a Mente release artifact flow, not `git clone` of moving `main`
- install/update bootstrap the matching vendored runtime artifact for that release
- `setup-hermes.sh` is explicitly treated as a developer/source-checkout path, not the frozen end-user install path
- managed installs continue to delegate updates to the package manager
- offline/local-asset bootstrap is possible for tests and rollback drills

**Step 2: Run test to verify it fails**

Run:

```bash
scripts/run_tests.sh tests/hermes_cli/test_mente_runtime_bootstrap.py tests/hermes_cli/test_update_autostash.py -v
```

Expected:
- FAIL because install/update still assume git branch updates and do not bootstrap a release-matched vendored runtime artifact

**Step 3: Write minimal implementation**

Update install/update/bootstrap policy so that:
- end-user one-click install is release-pinned
- the matching frozen vendored runtime artifact is installed/bootstraped automatically
- `hermes update` upgrades release-to-release and refreshes the vendored runtime artifact in lockstep
- managed installs keep using package-manager-native upgrade commands
- source-checkout developer setup remains available but is clearly separated from release installs

Do not make the installer fetch arbitrary upstream Codex state at install time.

**Step 4: Run test to verify it passes**

Run:

```bash
scripts/run_tests.sh tests/hermes_cli/test_mente_runtime_bootstrap.py tests/hermes_cli/test_update_autostash.py -v
uv run python -m compileall hermes_cli
```

Expected:
- tests PASS
- `compileall` exit code `0`

**Step 5: Commit**

```bash
git add scripts/install.sh scripts/install.ps1 setup-hermes.sh README.md hermes_cli/main.py hermes_cli/config.py tests/hermes_cli/test_mente_runtime_bootstrap.py
git commit -m "feat: bootstrap frozen vendored codex runtime during install and update"
```

### Task 6: Codify Patch Policy, Upgrade Policy, Verification Matrix, And Rollback Boundary

**Files:**
- Create: `kernel/codex/patches/README.md`
- Create: `docs/plans/2026-04-30-mente-codex-patch-policy.md`
- Create: `docs/plans/2026-04-30-mente-codex-upgrade-policy.md`
- Create: `docs/plans/2026-04-30-mente-c6-verification-and-rollback.md`
- Modify: `docs/plans/2026-04-30-mente-codex-upstream-snapshot-manifest.md`
- Modify: `docs/plans/2026-04-30-mente-phase-c4-cutover-manifest.md`
- Modify: `docs/plans/2026-04-30-mente-phase-c5-capability-boundary-manifest.md`
- Modify: `tests/mente/test_codex_snapshot.py`
- Modify: `tests/mente/test_kernel_inventory.py`

**Step 1: Write the failing test**

Add tests that assert C6 policy and rollback docs exist and record:
- what counts as an upstream snapshot upgrade vs a same-snapshot Mente patch
- where patches are allowed (`kernel/codex/patches/` and bridge/release surfaces) and where they are not (`kernel/codex/upstream/` by default)
- required release verification before shipping a frozen runtime
- explicit rollback inputs: prior release id, prior runtime artifact manifest, and operator override boundaries

**Step 2: Run test to verify it fails**

Run:

```bash
scripts/run_tests.sh tests/mente/test_codex_snapshot.py tests/mente/test_kernel_inventory.py tests/mente/test_codex_release_freeze.py -v
```

Expected:
- FAIL because the C6 patch/upgrade/rollback policy docs and patch-root marker do not exist yet

**Step 3: Write minimal implementation**

Create the policy docs and freeze the boundary explicitly:
- default: no edits inside vendored upstream tree
- allowed patches: bridge/release/runtime compatibility work outside upstream, or rare emergency upstream-tree edits recorded with rationale and drop criteria
- upgrade policy: new upstream snapshot requires a dedicated C3/C4/C5/C6 re-verification pass
- rollback policy: revert by prior Mente release + prior frozen vendored runtime artifact, not by re-enabling public `codex`

**Step 4: Run verification**

Run:

```bash
scripts/run_tests.sh tests/mente/test_codex_snapshot.py tests/mente/test_kernel_inventory.py tests/mente/test_codex_release_freeze.py tests/mente/test_release_packaging.py tests/hermes_cli/test_mente_runtime_bootstrap.py -v
uv run python -m compileall kernel/codex mente hermes_cli
```

Expected:
- tests PASS
- `compileall` exit code `0`

**Step 5: Commit**

```bash
git add kernel/codex/patches/README.md docs/plans/2026-04-30-mente-codex-patch-policy.md docs/plans/2026-04-30-mente-codex-upgrade-policy.md docs/plans/2026-04-30-mente-c6-verification-and-rollback.md docs/plans/2026-04-30-mente-codex-upstream-snapshot-manifest.md docs/plans/2026-04-30-mente-phase-c4-cutover-manifest.md docs/plans/2026-04-30-mente-phase-c5-capability-boundary-manifest.md tests/mente/test_codex_snapshot.py tests/mente/test_kernel_inventory.py
git commit -m "docs: freeze codex patch and release policy boundary"
```

### Final Verification

Run:

```bash
scripts/run_tests.sh tests/mente/test_codex_bridge.py tests/mente/test_codex_executor.py tests/mente/test_kernel_runner.py tests/mente/test_codex_release_freeze.py tests/mente/test_release_packaging.py tests/mente/test_codex_snapshot.py tests/mente/test_kernel_inventory.py tests/test_project_metadata.py tests/hermes_cli/test_mente_runtime_bootstrap.py tests/hermes_cli/test_update_autostash.py -v
uv run python -m build
uv run python -m compileall kernel/codex mente hermes_cli
```

C6 is complete only if:
- the production main path does not rely on an ambient public `codex` binary
- vendored Codex runtime resolution is release-frozen and bootstrapable
- Mente release artifacts include the vendored kernel slice
- installer/update flows operate on release-pinned assets instead of moving branch head
- patch and upgrade policy are explicit and auditable
- rollback is defined in terms of prior Mente release artifacts, not public `codex`
- `CodexKernelAdapter` remains the only upper-layer seam
- no product logic was pushed into `kernel/codex/upstream/`
