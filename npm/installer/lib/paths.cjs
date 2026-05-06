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

function getBootstrapInstallArgs(env = process.env) {
  const release = String(env.MENTE_BOOTSTRAP_RELEASE || '').trim();
  if (release) {
    return ['--release', release];
  }

  const branch = String(env.MENTE_BOOTSTRAP_BRANCH || '').trim() || 'main';
  return ['--branch', branch];
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

function getInstalledBinaryCandidates(env = process.env) {
  const candidates = [];
  const menteHome = getEffectiveMenteHome(env);
  if (menteHome) {
    candidates.push(path.join(menteHome, 'mente-agent', 'venv', 'bin', 'mente'));
    candidates.push(path.join(menteHome, 'mente-agent', '.venv', 'bin', 'mente'));
    candidates.push(path.join(menteHome, 'mente-agent', 'venv', 'Scripts', 'mente.exe'));
    candidates.push(path.join(menteHome, 'mente-agent', '.venv', 'Scripts', 'mente.exe'));
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

module.exports = {
  findInstalledMenteBinary,
  getBundledInstallCmdScript,
  getBundledInstallPowerShellScript,
  getBundledInstallScript,
  getBootstrapInstallArgs,
  getEffectiveMenteHome,
  getInstalledBinaryCandidates,
  getPackageRoot,
};
