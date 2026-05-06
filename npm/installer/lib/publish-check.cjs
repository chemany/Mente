'use strict';

function getExpectedPublishTag(version) {
  if (!version || typeof version !== 'string') {
    throw new Error('package version is required');
  }
  return `npm-v${version}`;
}

function validatePublishContext({
  eventName,
  refType,
  refName,
  packageName,
  packageVersion,
  expectedVersion,
} = {}) {
  if (!packageName) {
    throw new Error('package name is required');
  }
  if (!packageVersion) {
    throw new Error('package version is required');
  }

  const expectedTag = getExpectedPublishTag(packageVersion);
  if (expectedVersion && expectedVersion !== packageVersion) {
    throw new Error(
      `expected version ${expectedVersion} does not match package.json version ${packageVersion}`,
    );
  }

  if (eventName === 'push' && refType === 'tag') {
    if (refName !== expectedTag) {
      throw new Error(
        `release tag ${refName} does not match package.json version ${packageVersion}; expected ${expectedTag}`,
      );
    }
    return {
      mode: 'publish',
      shouldPublish: true,
      packageName,
      packageVersion,
      expectedTag,
    };
  }

  return {
    mode: 'preflight',
    shouldPublish: false,
    packageName,
    packageVersion,
    expectedTag,
  };
}

module.exports = {
  getExpectedPublishTag,
  validatePublishContext,
};
