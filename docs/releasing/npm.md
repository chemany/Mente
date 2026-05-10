# NPM Release

This runbook is the shortest safe path to publish `mente-agent` to npm.

If this is the first public npm release for the package, run the dedicated checklist first: [npm-first-release-checklist.md](./npm-first-release-checklist.md).

## One-time setup

1. Log in to the `mente-agent` package owner account on npm.
2. Create a GitHub Actions repository secret named `NPM_TOKEN`.
3. Put an npm automation token with publish permission into `NPM_TOKEN`.

## Preflight

Run these locally from the repo root:

```bash
npm run test:npm-installer
npm run release:check:npm
npm pack --dry-run
```

The packaged private runtime currently ships with a default `codex.model_auto_compact_token_limit` of `160000`. If you intentionally change that default in code, update the docs and verification steps in the same release.

Optional GitHub-side preflight:

1. Open `Actions` -> `npm-publish`.
2. Click `Run workflow`.
3. Fill `expected_version` with the exact `package.json` version, for example `0.11.0`.
4. Run it and confirm the job ends at `Preflight summary`.

`workflow_dispatch` is preflight-only. It does not publish.

## Publish

If `package.json` says `0.11.0`, publish with:

```bash
git tag npm-v0.11.0
git push origin npm-v0.11.0
```

The workflow will:

1. verify tests,
2. verify the publish tag matches `package.json`,
3. verify the version is not already on npm,
4. run `npm publish --access public`.

## Verify release

```bash
npm view mente-agent version --registry=https://registry.npmjs.org
```

Then test the real install path:

```bash
npm install -g mente-agent
mente --help
```

Also verify the runtime-config docs still match the shipped default:

- `README.md`
- `README.zh.md`
- `website/docs/user-guide/configuration.md`

They should all describe the same default `codex.model_auto_compact_token_limit` value: `160000`.
