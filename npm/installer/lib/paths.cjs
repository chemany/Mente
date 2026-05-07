const fs = require('node:fs');
const path = require('node:path');

function getPackageRoot() {
  return path.resolve(__dirname, '../../..');
}

function getBundledInstallScript() {
  return path.join(getPackageRoot(), 'scripts', 'install.sh');
}

function getBundledInstallPowerShellScript() {
  return path.join(getPackageRoot(), 'scripts', 'install.ps1');
}

function getBundledInstallCmdScript() {
  return path.join(getPackageRoot(), 'scripts', 'install.cmd');
}

function getBundledRuntimeSourceTarball() {
  return path.join(
    getPackageRoot(),
    'npm',
    'installer',
    'bundles',
    'mente-runtime-source.tar.gz',
  );
}

function getBootstrapInstallArgs(env = process.env, options = {}) {
  const args = [];
  const release = String(env.MENTE_BOOTSTRAP_RELEASE || '').trim();
  if (release) {
    args.push('--release', release);
  } else {
    const branch = String(env.MENTE_BOOTSTRAP_BRANCH || '').trim() || 'main';
    args.push('--branch', branch);
  }

  if (options.skipSetup) {
    args.push('--skip-setup');
  }

  const chinaMode = String(env.MENTE_BOOTSTRAP_CHINA || '').trim().toLowerCase();
  if (chinaMode && !['0', 'false', 'no', 'off'].includes(chinaMode)) {
    args.push('--china');
  }

  const bundledSourceTarball = String(options.bundledSourceTarball || '').trim();
  if (bundledSourceTarball) {
    args.push('--source-tarball', bundledSourceTarball);
  }

  return args;
}

function getEffectiveMenteHome(env = process.env) {
  const menteHome = String(env.MENTE_HOME || '').trim();
  if (menteHome) {
    return menteHome;
  }
  const hermesHome = String(env.HERMES_HOME || '').trim();
  if (hermesHome) {
    return hermesHome;
  }
  const home = String(env.HOME || '').trim();
  return home ? path.join(home, '.mente') : '';
}

function getInstalledProjectRoot(env = process.env) {
  const menteHome = getEffectiveMenteHome(env);
  return menteHome ? path.join(menteHome, 'mente-agent') : '';
}

function getBootstrapStatePath(env = process.env) {
  const menteHome = getEffectiveMenteHome(env);
  return menteHome ? path.join(menteHome, '.mente-npm-bootstrap.json') : '';
}

function getInstalledBinaryCandidates(env = process.env) {
  const candidates = [];
  const projectRoot = getInstalledProjectRoot(env);
  if (projectRoot) {
    candidates.push(path.join(projectRoot, 'venv', 'bin', 'mente'));
    candidates.push(path.join(projectRoot, '.venv', 'bin', 'mente'));
    candidates.push(path.join(projectRoot, 'venv', 'Scripts', 'mente.exe'));
    candidates.push(path.join(projectRoot, '.venv', 'Scripts', 'mente.exe'));
  }

  const pathEntries = String(env.PATH || '')
    .split(path.delimiter)
    .map((entry) => entry.trim())
    .filter(Boolean);

  for (const entry of pathEntries) {
    candidates.push(path.join(entry, 'mente'));
    candidates.push(path.join(entry, 'mente.exe'));
    candidates.push(path.join(entry, 'mente.cmd'));
  }

  candidates.push('/usr/local/bin/mente');

  return [...new Set(candidates)];
}

function findInstalledMenteBinary(options = {}) {
  const env = options.env || process.env;
  const existsSync = options.existsSync || fs.existsSync;
  const skip = new Set((options.skip || []).map((candidate) => path.resolve(candidate)));

  for (const candidate of getInstalledBinaryCandidates(env)) {
    const resolved = path.resolve(candidate);
    if (skip.has(resolved)) {
      continue;
    }
    if (existsSync(candidate)) {
      return candidate;
    }
  }
  return null;
}

function shouldRefreshInstalledRuntime(options = {}) {
  const env = options.env || process.env;
  const existsSync = options.existsSync || fs.existsSync;
  const readFileSync = options.readFileSync || fs.readFileSync;
  const packageVersion = String(options.packageVersion || '').trim();
  const statePath = getBootstrapStatePath(env);

  if (!packageVersion || !statePath || !existsSync(statePath)) {
    return true;
  }

  try {
    const payload = JSON.parse(readFileSync(statePath, 'utf8'));
    return String(payload.package_version || '').trim() !== packageVersion;
  } catch {
    return true;
  }
}

module.exports = {
  findInstalledMenteBinary,
  getBootstrapStatePath,
  getBundledInstallCmdScript,
  getBundledInstallPowerShellScript,
  getBundledInstallScript,
  getBundledRuntimeSourceTarball,
  getBootstrapInstallArgs,
  getEffectiveMenteHome,
  getInstalledProjectRoot,
  getInstalledBinaryCandidates,
  getPackageRoot,
  shouldRefreshInstalledRuntime,
};
