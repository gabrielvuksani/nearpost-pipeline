import { test } from 'node:test';
import assert from 'node:assert/strict';
import { assessHealth } from '../src/health.js';
import {
  NOW, MINUTE, HOUR, iso, healthyStatus, captureTask, missedCapture,
} from '../test-support/fixtures.js';

const assess = (overrides, dispatchError = null) =>
  assessHealth({ status: healthyStatus(overrides) }, NOW, dispatchError);

const assertHealthy = (report) => assert.deepEqual(report, { ok: true, problems: [] });

function assertOneProblem(report, pattern) {
  assert.equal(report.ok, false);
  assert.equal(report.problems.length, 1, `problems: ${JSON.stringify(report.problems)}`);
  assert.match(report.problems[0], pattern);
}

test('a healthy status has no problems', () => {
  assertHealthy(assess({}));
});

test('missing, unparsable or unknown-schema status is a problem', () => {
  const report = assessHealth({ error: 'status.json is missing' }, NOW, null);
  assertOneProblem(report, /status\.json is missing/);
});

test('an unusable status still reports the dispatch error', () => {
  const report = assessHealth({ error: 'bad' }, NOW, 'HTTP 500');
  assert.equal(report.problems.length, 2);
});

test('generated_at: exactly 26h old is fine, older is a problem', () => {
  assertHealthy(assess({ generated_at: iso(NOW - 26 * HOUR) }));
  assertOneProblem(assess({ generated_at: iso(NOW - 26 * HOUR - 1000) }), /generated_at/);
});

test('last_success.daily missing is a problem', () => {
  assertOneProblem(assess({ last_success: { tick: iso(NOW) } }), /last_success\.daily is missing/);
  assertOneProblem(assess({ last_success: { daily: null } }), /last_success\.daily is missing/);
});

test('last_success.daily: exactly 26h old is fine, older is a problem', () => {
  assertHealthy(assess({ last_success: { daily: iso(NOW - 26 * HOUR) } }));
  assertOneProblem(
    assess({ last_success: { daily: iso(NOW - 26 * HOUR - 1000) } }),
    /last_success\.daily/,
  );
});

test('a missing last_success.tick is not a problem', () => {
  assertHealthy(assess({ last_success: { daily: iso(NOW - HOUR) } }));
});

test('task overdue: exactly 40 min past due is fine, later is a problem', () => {
  assertHealthy(assess({ tasks: [captureTask(NOW - 40 * MINUTE)] }));
  assertOneProblem(
    assess({ tasks: [captureTask(NOW - 40 * MINUTE - 1000)] }),
    /overdue.*capture 2026-27:arsenal-v-chelsea T-24h/,
  );
});

test('future and recently due tasks are fine', () => {
  assertHealthy(assess({ tasks: [captureTask(NOW - 5 * MINUTE), captureTask(NOW + HOUR)] }));
});

test('overdue fpl-deadline task is described by gameweek', () => {
  const task = { kind: 'fpl-deadline', due_at: iso(NOW - HOUR), gameweek: 6 };
  assertOneProblem(assess({ tasks: [task] }), /fpl-deadline GW6/);
});

test('missed: closed exactly 24h ago is a problem, older is fine', () => {
  assertOneProblem(assess({ missed: [missedCapture(NOW - 24 * HOUR)] }), /missed.*fulham-v-hull-city/);
  assertHealthy(assess({ missed: [missedCapture(NOW - 24 * HOUR - 1000)] }));
});

test('missed: closed a minute ago is a problem', () => {
  assertOneProblem(assess({ missed: [missedCapture(NOW - MINUTE)] }), /missed/);
});

test('odds credits: 25 is fine, 24 is a problem', () => {
  assertHealthy(assess({ odds_api: { credits_remaining: 25, observed_at: iso(NOW) } }));
  assertOneProblem(
    assess({ odds_api: { credits_remaining: 24, observed_at: iso(NOW) } }),
    /credits.*24/,
  );
});

test('odds_api null is fine', () => {
  assertHealthy(assess({ odds_api: null }));
});

test('a dispatch error is a problem and is included verbatim', () => {
  assertOneProblem(assess({}, 'GitHub dispatch (tick) failed: HTTP 422'), /HTTP 422/);
});

test('problems accumulate', () => {
  const report = assess(
    {
      generated_at: iso(NOW - 30 * HOUR),
      last_success: {},
      tasks: [captureTask(NOW - 2 * HOUR)],
      missed: [missedCapture(NOW - HOUR)],
      odds_api: { credits_remaining: 3, observed_at: iso(NOW) },
    },
    'boom',
  );
  assert.equal(report.problems.length, 6);
});
