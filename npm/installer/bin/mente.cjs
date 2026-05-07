#!/usr/bin/env node

const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');

const {
  findInstalledMenteBinary,
  getBootstrapInstallArgs,
  getBootstrapStatePath,
  getBundledInstallPowerShellScript,
  getBundledInstallScript,
  getBundledRuntimeSourceTarball,
  getEffectiveMenteHome,
  shouldRefreshInstalledRuntime,
} = require('../lib/paths.cjs');
const pkg = require('../../../package.json');

function isSameExecutable(a, b) {
  if (!a || !b) {
    return false;
  }
  try {
    return fs.realpathSync(a) === fs.realpathSync(b);
  } catch {
    return path.resolve(a) === path.resolve(b);
  }
}

function run(command, args, options = {}) {
  const result = spawnSync(command, args, {
    stdio: 'inherit',
    env: process.env,
    ...options,
  });
  if (result.error) {
    throw result.error;
  }
  return result.status ?? 1;
}

function bootstrapInstall(options = {}) {
  const bundledSourceTarball = getBundledRuntimeSourceTarball();
  const installArgs = getBootstrapInstallArgs(process.env, {
    ...options,
    bundledSourceTarball: fs.existsSync(bundledSourceTarball)
      ? bundledSourceTarball
      : '',
  });

  if (process.platform === 'win32') {
    const powershellScript = getBundledInstallPowerShellScript();
    return run('powershell', [
      '-ExecutionPolicy',
      'Bypass',
      '-File',
      powershellScript,
      ...installArgs,
    ]);
  }

  const installScript = getBundledInstallScript();
  return run('bash', [installScript, ...installArgs]);
}

function writeBootstrapState() {
  const menteHome = getEffectiveMenteHome(process.env);
  const statePath = getBootstrapStatePath(process.env);
  if (!menteHome || !statePath) {
    return;
  }

  fs.mkdirSync(menteHome, { recursive: true });
  fs.writeFileSync(
    statePath,
    `${JSON.stringify({ package_version: pkg.version }, null, 2)}\n`,
    'utf8',
  );
}

function main() {
  const selfPath = process.argv[1];
  const menteBinary = findInstalledMenteBinary({
    skip: [selfPath],
  });

  if (menteBinary && !isSameExecutable(menteBinary, selfPath)) {
    if (shouldRefreshInstalledRuntime({ packageVersion: pkg.version })) {
      console.error(`Mente runtime is older than mente-agent@${pkg.version}. Updating installed runtime...`);
      const updateExitCode = bootstrapInstall({ skipSetup: true });
      if (updateExitCode !== 0) {
        console.error('Mente runtime update failed; launching the existing runtime instead.');
      } else {
        writeBootstrapState();
      }
    }

    const refreshedBinary = findInstalledMenteBinary({
      skip: [selfPath],
    }) || menteBinary;
    const exitCode = run(refreshedBinary, process.argv.slice(2));
    process.exit(exitCode);
  }

  console.error('Mente runtime not found. Bootstrapping the full installer...');
  const installExitCode = bootstrapInstall();
  if (installExitCode !== 0) {
    process.exit(installExitCode);
  }
  writeBootstrapState();

  const installedBinary = findInstalledMenteBinary({
    skip: [selfPath],
  });
  if (!installedBinary || isSameExecutable(installedBinary, selfPath)) {
    console.error('Mente installer completed, but the runtime binary could not be located.');
    console.error(`Expected install script: ${getBundledInstallScript()}`);
    process.exit(1);
  }

  const exitCode = run(installedBinary, process.argv.slice(2));
  process.exit(exitCode);
}

main();
