import { test } from 'node:test';
import assert from 'node:assert/strict';
import { parseStatus } from '../src/status.js';
import { healthyStatus, captureTask, missedCapture, NOW } from '../test-support/fixtures.js';

const text = (overrides) => JSON.stringify(healthyStatus(overrides));

function assertError(result, pattern) {
  assert.equal(result.status, undefined);
  assert.match(result.error, pattern);
}

test('valid status parses to an equal object', () => {
  const status = healthyStatus({ tasks: [captureTask(NOW)], missed: [missedCapture(NOW)] });
  assert.deepEqual(parseStatus(JSON.stringify(status)), { status });
});

test('the contract example parses', () => {
  const example = {
    schema: 1,
    generated_at: '2026-10-09T06:02:11Z',
    last_success: { daily: '2026-10-09T06:02:11Z', tick: '2026-10-08T19:45:40Z' },
    tasks: [
      { kind: 'capture', due_at: '2026-10-09T11:30:00Z', match_id: 'x', horizon: 'T-24h', kickoff: '2026-10-10T11:30:00Z' },
      { kind: 'fpl-deadline', due_at: '2026-10-10T09:00:00Z', gameweek: 6 },
    ],
    missed: [{ kind: 'capture', match_id: 'y', horizon: 'T-1h', window_closed_at: '2026-10-10T13:45:00Z' }],
    odds_api: { credits_remaining: 431, observed_at: '2026-10-08T19:45:38Z' },
  };
  assert.deepEqual(parseStatus(JSON.stringify(example)), { status: example });
});

test('fractional seconds are accepted', () => {
  assert.ok(parseStatus(text({ generated_at: '2026-10-10T11:55:00.123456Z' })).status);
});

test('bad JSON is an error', () => {
  assertError(parseStatus('{"schema": 1,'), /not valid JSON/);
  assertError(parseStatus(''), /not valid JSON/);
});

test('non-object JSON is an error', () => {
  for (const body of ['null', '[]', '42', '"x"']) assertError(parseStatus(body), /object/);
});

test('wrong or missing schema is an error', () => {
  assertError(parseStatus(text({ schema: 2 })), /schema/);
  assertError(parseStatus(text({ schema: '1' })), /schema/);
  assertError(parseStatus(text({ schema: undefined })), /schema/);
});

test('generated_at must be an ISO UTC timestamp', () => {
  assertError(parseStatus(text({ generated_at: undefined })), /generated_at/);
  assertError(parseStatus(text({ generated_at: 'yesterday' })), /generated_at/);
  assertError(parseStatus(text({ generated_at: '2026-10-10T12:00:00+01:00' })), /generated_at/);
  assertError(parseStatus(text({ generated_at: '2026-13-40T12:00:00Z' })), /generated_at/);
});

test('last_success must be an object whose keys are ISO timestamps, null or absent', () => {
  assertError(parseStatus(text({ last_success: undefined })), /last_success/);
  assertError(parseStatus(text({ last_success: null })), /last_success/);
  assertError(parseStatus(text({ last_success: { daily: 'soon' } })), /last_success\.daily/);
  assertError(parseStatus(text({ last_success: { tick: 5 } })), /last_success\.tick/);
  assert.ok(parseStatus(text({ last_success: {} })).status);
  assert.ok(parseStatus(text({ last_success: { daily: null } })).status);
});

test('tasks and missed must be arrays', () => {
  assertError(parseStatus(text({ tasks: undefined })), /tasks/);
  assertError(parseStatus(text({ tasks: {} })), /tasks/);
  assertError(parseStatus(text({ missed: undefined })), /missed/);
  assertError(parseStatus(text({ missed: 'none' })), /missed/);
});

test('each task needs a kind and an ISO due_at', () => {
  assertError(parseStatus(text({ tasks: [{ kind: 'capture' }] })), /tasks\[0\]\.due_at/);
  assertError(parseStatus(text({ tasks: [{ due_at: '2026-10-10T12:00:00Z' }] })), /tasks\[0\]\.kind/);
  assertError(parseStatus(text({ tasks: [null] })), /tasks\[0\]/);
});

test('each missed entry needs a kind and an ISO window_closed_at', () => {
  assertError(
    parseStatus(text({ missed: [{ kind: 'capture', window_closed_at: 'x' }] })),
    /missed\[0\]\.window_closed_at/,
  );
});

test('odds_api must be null or carry numeric credits and an ISO observed_at', () => {
  assert.ok(parseStatus(text({ odds_api: null })).status);
  assertError(parseStatus(text({ odds_api: undefined })), /odds_api/);
  assertError(parseStatus(text({ odds_api: { credits_remaining: '9', observed_at: '2026-10-10T12:00:00Z' } })), /credits_remaining/);
  assertError(parseStatus(text({ odds_api: { credits_remaining: 9 } })), /observed_at/);
});
