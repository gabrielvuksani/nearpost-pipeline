import { test } from 'node:test';
import assert from 'node:assert/strict';
import { findMissingConfig, REQUIRED_CONFIG } from '../src/config.js';
import { fakeEnv } from '../test-support/fakes.js';

test('a complete env has nothing missing', () => {
  assert.deepEqual(findMissingConfig(fakeEnv()), []);
});

test('every required name is reported when absent', () => {
  assert.deepEqual(findMissingConfig({}), REQUIRED_CONFIG);
  assert.deepEqual(REQUIRED_CONFIG, [
    'GITHUB_REPO', 'WORKFLOW_FILE', 'GITHUB_TOKEN', 'HC_PING_KEY', 'BUCKET', 'STATE',
  ]);
});

test('empty or whitespace-only strings count as missing', () => {
  assert.deepEqual(findMissingConfig(fakeEnv({ GITHUB_TOKEN: '', HC_PING_KEY: '  ' })), [
    'GITHUB_TOKEN', 'HC_PING_KEY',
  ]);
});
