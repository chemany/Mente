import test from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import pkg from '../../package.json' with { type: 'json' };
import installerPaths from '../../npm/installer/lib/paths.cjs';

const {
  findInstalledMenteBinary,
  getBootstrapInstallArgs,
  getBundledInstallScript,
  getPackageRoot,
} = installerPaths;

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

test('installer helper resolves package root and bundled install script', () => {
  const packageRoot = getPackageRoot();
  assert.equal(packageRoot, path.resolve(__dirname, '../..'));
  assert.equal(
    getBundledInstallScript(),
    path.join(packageRoot, 'scripts', 'install.sh'),
  );
});

test('installer helper exposes installed binary candidates', () => {
  const result = findInstalledMenteBinary({
    env: {
      HOME: '/tmp/example-home',
      MENTE_HOME: '/tmp/example-home/.mente',
      HERMES_HOME: '/tmp/example-home/.hermes',
      PATH: '/usr/local/bin:/usr/bin',
    },
    existsSync: (candidate) =>
      candidate === '/tmp/example-home/.mente/mente-agent/venv/bin/mente',
  });

  assert.equal(result, '/tmp/example-home/.mente/mente-agent/venv/bin/mente');
});

test('installer helper defaults bootstrap install to main and allows release override', () => {
  assert.deepEqual(getBootstrapInstallArgs({}), ['--branch', 'main']);
  assert.deepEqual(
    getBootstrapInstallArgs({ MENTE_BOOTSTRAP_RELEASE: 'v0.11.0' }),
    ['--release', 'v0.11.0'],
  );
});

test('package metadata is publishable and locked down', () => {
  assert.equal(pkg.name, 'mente-agent');
  assert.equal(pkg.private, undefined);
  assert.equal(pkg.bin.mente, 'npm/installer/bin/mente.cjs');
  assert.equal(pkg.bin['mente-agent'], 'npm/installer/bin/mente.cjs');
  assert.equal(pkg.repository.url, 'git+https://github.com/chemany/Mente.git');
  assert.equal(pkg.bugs.url, 'https://github.com/chemany/Mente/issues');
  assert.equal(pkg.homepage, 'https://github.com/chemany/Mente#readme');

  for (const requiredEntry of [
    'npm/installer/bin',
    'npm/installer/lib',
    'scripts/install.sh',
    'scripts/install.ps1',
    'scripts/install.cmd',
    'README.md',
    'LICENSE',
  ]) {
    assert.ok(
      pkg.files.includes(requiredEntry),
      `missing published file entry: ${requiredEntry}`,
    );
  }
});
