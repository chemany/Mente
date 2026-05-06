#!/usr/bin/env node

const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');

const {
  findInstalledMenteBinary,
  getBootstrapInstallArgs,
  getBundledInstallPowerShellScript,
  getBundledInstallScript,
} = require('../lib/paths.cjs');

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

function bootstrapInstall() {
  if (process.platform === 'win32') {
    const powershellScript = getBundledInstallPowerShellScript();
    return run('powershell', [
      '-ExecutionPolicy',
      'Bypass',
      '-File',
      powershellScript,
      ...getBootstrapInstallArgs(),
    ]);
  }

  const installScript = getBundledInstallScript();
  return run('bash', [installScript, ...getBootstrapInstallArgs()]);
}

function main() {
  const selfPath = process.argv[1];
  const menteBinary = findInstalledMenteBinary({
    skip: [selfPath],
  });

  if (menteBinary && !isSameExecutable(menteBinary, selfPath)) {
    const exitCode = run(menteBinary, process.argv.slice(2));
    process.exit(exitCode);
  }

  console.error('Mente runtime not found. Bootstrapping the full installer...');
  const installExitCode = bootstrapInstall();
  if (installExitCode !== 0) {
    process.exit(installExitCode);
  }

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
