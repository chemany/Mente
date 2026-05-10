# First NPM Release Checklist

This checklist is for the **first public npm release** of `mente-agent`.

Use it together with [npm.md](./npm.md).

As of May 7, 2026, the package release path in this repo is:

1. set `NPM_TOKEN`,
2. run GitHub preflight if needed,
3. push `npm-v<package-version>` tag,
4. let GitHub Actions publish to npm.

---

## 1. npm account permissions

- [ ] You can log in to the npm account that will publish `mente-agent`.
- [ ] That npm account is the correct long-term owner for this package name.
- [ ] If `mente-agent` already exists on npm, this account already has publish permission for it.
- [ ] If `mente-agent` does not exist yet, this account is the one that should create the package on first publish.
- [ ] If you publish through an npm organization, confirm the user account is actually allowed to publish the package itself, not just manage org settings.
- [ ] If your npm account has 2FA enabled for writes, confirm your CI token strategy is compatible before tagging a release.

## 2. `NPM_TOKEN` type and scope

- [ ] Use an npm **granular access token**.
- [ ] Do **not** use an old legacy token flow.
- [ ] The token has **read and write** access, not read-only.
- [ ] The token is scoped to the exact package or scope needed for `mente-agent`.
- [ ] The token expiration date is long enough to survive the planned release window.
- [ ] If your npm setup requires 2FA for publish, verify whether the token must enable **Bypass 2FA for write actions**.
- [ ] Only enable **Bypass 2FA** if your package policy and org policy allow it.
- [ ] Copy the token value once when npm shows it; store it immediately in GitHub Secrets.
- [ ] After saving the token in GitHub, do not keep the raw token in shell history, chat logs, or local notes.

## 3. GitHub secret setup

- [ ] You have GitHub access that can edit repository Actions secrets for `chemany/Mente`.
- [ ] In GitHub, open `Settings` -> `Secrets and variables` -> `Actions`.
- [ ] Create a new **repository secret** named `NPM_TOKEN`.
- [ ] Paste the npm granular token as the secret value.
- [ ] Confirm the secret name is exactly `NPM_TOKEN`.
- [ ] Do not use a repo variable for this; it must be a secret.

## 4. GitHub Actions workflow page checks

- [ ] The branch you are releasing from is the default branch and contains `.github/workflows/npm-publish.yml`.
- [ ] In GitHub, open `Actions` and confirm the `npm-publish` workflow is visible.
- [ ] Confirm you have enough repository access to manually run workflows.
- [ ] Open the `npm-publish` workflow page and verify it shows the `Run workflow` button.
- [ ] Understand that `Run workflow` is **preflight only** in this repo and does not publish.
- [ ] If using preflight, fill `expected_version` with the exact `package.json` version, for example `0.11.0`.
- [ ] Confirm the preflight run reaches the `Preflight summary` step successfully.
- [ ] Read the logs and verify:
  - [ ] the package version is the one you intend to release;
  - [ ] the expected tag is `npm-v<that-version>`;
  - [ ] the version is not already published.

## 5. Local release-state checks before tag push

- [ ] `package.json` version is final.
- [ ] `pyproject.toml` version is aligned if this release should keep Python and npm versions in sync.
- [ ] `npm run test:npm-installer` passes.
- [ ] `npm run release:check:npm` passes.
- [ ] `npm pack --dry-run` passes.
- [ ] Runtime-config docs still match the shipped default `codex.model_auto_compact_token_limit` value (`160000`).
- [ ] Your local branch is up to date with `origin/main`.
- [ ] There is no accidental dirty diff you do not want to ship.

## 6. First publish action

- [ ] Create the tag that exactly matches the package version:

```bash
git tag npm-v0.11.0
git push origin npm-v0.11.0
```

- [ ] Open the Actions run triggered by the tag push.
- [ ] Confirm the workflow passes the validation step.
- [ ] Confirm it does **not** fail on the duplicate-version check.
- [ ] Confirm the final `Publish package` step succeeds.

## 7. Post-release verification

- [ ] Run:

```bash
npm view mente-agent version --registry=https://registry.npmjs.org
```

- [ ] Confirm npm returns the just-published version.
- [ ] Test the real user install flow on a clean machine:

```bash
npm install -g mente-agent
mente --help
```

- [ ] If install still fails, inspect the Actions publish logs before changing README wording.
