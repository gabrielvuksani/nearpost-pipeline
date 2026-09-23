import { test } from 'node:test';
import assert from 'node:assert/strict';
import { decideDispatch } from '../src/decide.js';
import { NOW, MINUTE, HOUR, healthyStatus, captureTask } from '../test-support/fixtures.js';

const withTasks = (...dueTimes) => healthyStatus({ tasks: dueTimes.map((t) => captureTask(t)) });

test('no status (missing or invalid) never dispatches', () => {
  assert.equal(decideDispatch(null, NOW, null), false);
});

test('no tasks: no dispatch', () => {
  assert.equal(decideDispatch(withTasks(), NOW, null), false);
});

test('only future tasks: no dispatch', () => {
  assert.equal(decideDispatch(withTasks(NOW + 1, NOW + HOUR), NOW, null), false);
});

test('newly due task with no previous dispatch: dispatch', () => {
  assert.equal(decideDispatch(withTasks(NOW - MINUTE, NOW + HOUR), NOW, null), true);
});

test('a task due exactly now counts as due', () => {
  assert.equal(decideDispatch(withTasks(NOW), NOW, null), true);
});

test('due task already covered by a recent dispatch: no re-dispatch', () => {
  const lastDispatch = NOW - 10 * MINUTE;
  assert.equal(decideDispatch(withTasks(NOW - 12 * MINUTE), NOW, lastDispatch), false);
});

test('a task due at exactly the last dispatch time is not new work', () => {
  const lastDispatch = NOW - 10 * MINUTE;
  assert.equal(decideDispatch(withTasks(lastDispatch), NOW, lastDispatch), false);
});

test('retry once the last dispatch is 30 minutes old', () => {
  const status = withTasks(NOW - 40 * MINUTE);
  assert.equal(decideDispatch(status, NOW, NOW - 29 * MINUTE), false);
  assert.equal(decideDispatch(status, NOW, NOW - 30 * MINUTE), true);
});

test('new task falling due after the last dispatch triggers inside 30 minutes', () => {
  const lastDispatch = NOW - 10 * MINUTE;
  const status = withTasks(NOW - 12 * MINUTE, lastDispatch + MINUTE);
  assert.equal(decideDispatch(status, NOW, lastDispatch), true);
});

test('future tasks never count as new work', () => {
  const lastDispatch = NOW - 10 * MINUTE;
  const status = withTasks(NOW - 12 * MINUTE, NOW + MINUTE);
  assert.equal(decideDispatch(status, NOW, lastDispatch), false);
});
