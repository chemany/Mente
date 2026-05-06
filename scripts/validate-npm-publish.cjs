#!/usr/bin/env node
'use strict';

const fs = require('node:fs');
const path = require('node:path');

const pkg = require('../package.json');
const {
  validatePublishContext,
} = require('../npm/installer/lib/publish-check.cjs');

function parseArgs(argv) {
  const result = {};
  for (let index = 0; index < argv.length; index += 1) {
    const token = argv[index];
    if (!token.startsWith('--')) {
      continue;
    }
    const key = token.slice(2);
    const next = argv[index + 1];
    if (!next || next.startsWith('--')) {
      result[key] = true;
      continue;
    }
    result[key] = next;
    index += 1;
  }
  return result;
}

function writeGithubOutput(filePath, payload) {
  if (!filePath) {
    return;
  }
  const lines = Object.entries(payload).map(([key, value]) => `${key}=${value}`);
  fs.appendFileSync(filePath, `${lines.join('\n')}\n`, 'utf8');
}

function main() {
  const args = parseArgs(process.argv.slice(2));
  const result = validatePublishContext({
    eventName: args.event || process.env.GITHUB_EVENT_NAME || 'workflow_dispatch',
    refType: args['ref-type'] || process.env.GITHUB_REF_TYPE || '',
    refName: args['ref-name'] || process.env.GITHUB_REF_NAME || '',
    expectedVersion: args['expected-version'] || process.env.INPUT_EXPECTED_VERSION || '',
    packageName: pkg.name,
    packageVersion: pkg.version,
  });

  const payload = {
    package_name: result.packageName,
    package_version: result.packageVersion,
    expected_tag: result.expectedTag,
    mode: result.mode,
    should_publish: String(result.shouldPublish),
  };
  writeGithubOutput(args['github-output'] || process.env.GITHUB_OUTPUT, payload);
  process.stdout.write(`${JSON.stringify(payload, null, 2)}\n`);
}

try {
  main();
} catch (error) {
  const message = error instanceof Error ? error.message : String(error);
  process.stderr.write(`npm publish validation failed: ${message}\n`);
  process.exit(1);
}
