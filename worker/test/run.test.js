import { test } from 'node:test';
import assert from 'node:assert/strict';
import { runTick, runDaily, LAST_TICK_KEY } from '../src/run.js';
import { NOW, MINUTE, HOUR, iso, healthyStatus, captureTask } from '../test-support/fixtures.js';
import {
  fakeBucket, throwingBucket, fakeKv, fakeFetch, fakeEnv, TOKEN, PING_KEY,
} from '../test-support/fakes.js';

const deps = (fetch = fakeFetch()) => ({ fetch, now: () => NOW });
const statusText = (overrides = {}) => JSON.stringify(healthyStatus(overrides));
const dueNow = () => statusText({ tasks: [captureTask(NOW - MINUTE)] });

const githubCalls = (fetch) => fetch.calls.filter((c) => c.url.startsWith('https://api.github.com/'));
const pingCalls = (fetch) => fetch.calls.filter((c) => c.url.startsWith('https://hc-ping.com/'));

function silenceConsole(t) {
  return {
    error: t.mock.method(console, 'error', () => {}),
    log: t.mock.method(console, 'log', () => {}),
  };
}

const logged = (mock) => mock.mock.calls.map((c) => c.arguments.join(' ')).join('\n');

test('tick: due task with no previous dispatch dispatches, records KV, pings success', async (t) => {
  silenceConsole(t);
  const fetch = fakeFetch();
  const env = fakeEnv({ BUCKET: fakeBucket(dueNow()) });

  const report = await runTick(env, deps(fetch));

  assert.deepEqual(report, { ok: true, problems: [] });
  assert.deepEqual(env.BUCKET.reads, ['state/status.json']);
  const [dispatch] = githubCalls(fetch);
  assert.deepEqual(JSON.parse(dispatch.init.body), { ref: 'main', inputs: { mode: 'tick' } });
  assert.equal(env.STATE.store.get(LAST_TICK_KEY), iso(NOW));
  assert.equal(pingCalls(fetch)[0].url, `https://hc-ping.com/${PING_KEY}/nearpost-watchdog?create=1`);
});

test('tick: nothing due means no dispatch and no KV write', async (t) => {
  silenceConsole(t);
  const fetch = fakeFetch();
  const env = fakeEnv({ BUCKET: fakeBucket(statusText({ tasks: [captureTask(NOW + HOUR)] })) });

  const report = await runTick(env, deps(fetch));

  assert.equal(report.ok, true);
  assert.equal(githubCalls(fetch).length, 0);
  assert.equal(env.STATE.store.size, 0);
  assert.equal(pingCalls(fetch).length, 1);
});

test('tick: a recent dispatch in KV suppresses a re-dispatch', async (t) => {
  silenceConsole(t);
  const fetch = fakeFetch();
  const env = fakeEnv({
    BUCKET: fakeBucket(dueNow()),
    STATE: fakeKv({ [LAST_TICK_KEY]: iso(NOW - 30 * 1000) }),
  });

  await runTick(env, deps(fetch));

  assert.equal(githubCalls(fetch).length, 0);
});

test('tick: GitHub failure is reported to healthchecks without the token', async (t) => {
  silenceConsole(t);
  const fetch = fakeFetch((url) =>
    url.startsWith('https://api.github.com/')
      ? new Response(`boom ${TOKEN}`, { status: 500 })
      : new Response('OK'),
  );
  const env = fakeEnv({ BUCKET: fakeBucket(dueNow()) });

  const report = await runTick(env, deps(fetch));

  assert.equal(report.ok, false);
  assert.equal(env.STATE.store.size, 0, 'no KV write after a failed dispatch');
  const [ping] = pingCalls(fetch);
  assert.match(ping.url, /\/nearpost-watchdog\/fail\?create=1$/);
  assert.match(ping.init.body, /HTTP 500/);
  assert.ok(!ping.init.body.includes(TOKEN));
});

test('tick: missing status.json is a problem, not a crash', async (t) => {
  silenceConsole(t);
  const fetch = fakeFetch();
  const report = await runTick(fakeEnv({ BUCKET: fakeBucket(null) }), deps(fetch));

  assert.equal(report.ok, false);
  assert.match(report.problems.join('\n'), /state\/status\.json is missing/);
  assert.equal(githubCalls(fetch).length, 0);
  assert.match(pingCalls(fetch)[0].url, /\/fail\?create=1$/);
});

test('tick: an R2 read error is a problem, not a crash', async (t) => {
  silenceConsole(t);
  const report = await runTick(fakeEnv({ BUCKET: throwingBucket('r2 down') }), deps());
  assert.match(report.problems.join('\n'), /r2 down/);
});

test('tick: invalid status is a problem', async (t) => {
  silenceConsole(t);
  const report = await runTick(fakeEnv({ BUCKET: fakeBucket(statusText({ schema: 9 })) }), deps());
  assert.match(report.problems.join('\n'), /unknown schema 9/);
});

test('tick: missing GitHub config skips the dispatch and says so loudly', async (t) => {
  const console_ = silenceConsole(t);
  const fetch = fakeFetch();
  const env = fakeEnv({ BUCKET: fakeBucket(dueNow()), GITHUB_TOKEN: undefined });

  const report = await runTick(env, deps(fetch));

  assert.equal(githubCalls(fetch).length, 0);
  const problems = report.problems.join('\n');
  assert.match(problems, /missing configuration: GITHUB_TOKEN/);
  assert.match(problems, /tick dispatch needed but skipped/);
  assert.match(logged(console_.error), /GITHUB_TOKEN/);
  assert.equal(pingCalls(fetch).length, 1);
});

test('tick: missing HC_PING_KEY logs an error and does not throw', async (t) => {
  const console_ = silenceConsole(t);
  const fetch = fakeFetch();

  const report = await runTick(fakeEnv({ HC_PING_KEY: undefined, BUCKET: fakeBucket(statusText()) }), deps(fetch));

  assert.equal(pingCalls(fetch).length, 0);
  assert.match(report.problems.join('\n'), /HC_PING_KEY/);
  assert.match(logged(console_.error), /cannot ping healthchecks/);
});

test('tick: missing bindings are problems, not crashes', async (t) => {
  silenceConsole(t);
  const fetch = fakeFetch();
  const report = await runTick(fakeEnv({ BUCKET: undefined, STATE: undefined }), deps(fetch));
  assert.match(report.problems.join('\n'), /missing configuration: BUCKET, STATE/);
  assert.equal(pingCalls(fetch).length, 1);
});

test('tick: a failing ping is logged, never thrown, and never leaks the key', async (t) => {
  const console_ = silenceConsole(t);
  const fetch = fakeFetch((url) => {
    if (url.startsWith('https://hc-ping.com/')) throw new TypeError(`bad ${url}`);
    return new Response(null, { status: 204 });
  });

  await runTick(fakeEnv({ BUCKET: fakeBucket(statusText()) }), deps(fetch));

  const errors = logged(console_.error);
  assert.match(errors, /healthchecks ping network error/);
  assert.ok(!errors.includes(PING_KEY));
});

test('tick: a KV write failure after dispatch is reported', async (t) => {
  silenceConsole(t);
  const STATE = { get: async () => null, put: async () => { throw new Error('kv quota'); } };
  const report = await runTick(fakeEnv({ BUCKET: fakeBucket(dueNow()), STATE }), deps());
  assert.match(report.problems.join('\n'), /could not record tick dispatch.*kv quota/);
});

test('tick: a KV read failure is reported and treated as no previous dispatch', async (t) => {
  silenceConsole(t);
  const fetch = fakeFetch();
  const STATE = { get: async () => { throw new Error('kv down'); }, put: async () => {} };
  const report = await runTick(fakeEnv({ BUCKET: fakeBucket(dueNow()), STATE }), deps(fetch));
  assert.match(report.problems.join('\n'), /kv down/);
  assert.equal(githubCalls(fetch).length, 1);
});

test('tick: a corrupt KV timestamp is reported and treated as no previous dispatch', async (t) => {
  silenceConsole(t);
  const fetch = fakeFetch();
  const env = fakeEnv({ BUCKET: fakeBucket(dueNow()), STATE: fakeKv({ [LAST_TICK_KEY]: 'garbage' }) });
  const report = await runTick(env, deps(fetch));
  assert.match(report.problems.join('\n'), /invalid timestamp/);
  assert.equal(githubCalls(fetch).length, 1);
});

test('daily: dispatches unconditionally and does not touch the tick KV key', async (t) => {
  silenceConsole(t);
  const fetch = fakeFetch();
  const env = fakeEnv({ BUCKET: fakeBucket(statusText()) });

  const report = await runDaily(env, deps(fetch));

  assert.equal(report.ok, true);
  const [dispatch] = githubCalls(fetch);
  assert.deepEqual(JSON.parse(dispatch.init.body).inputs, { mode: 'daily' });
  assert.equal(env.STATE.store.size, 0);
  assert.equal(pingCalls(fetch).length, 1);
});

test('daily: dispatches even when status.json is missing, and reports it', async (t) => {
  silenceConsole(t);
  const fetch = fakeFetch();
  const report = await runDaily(fakeEnv(), deps(fetch));
  assert.equal(githubCalls(fetch).length, 1);
  assert.equal(report.ok, false);
});

test('daily: dispatch failure is a problem', async (t) => {
  silenceConsole(t);
  const fetch = fakeFetch((url) =>
    url.startsWith('https://api.github.com/') ? new Response('', { status: 404 }) : new Response('OK'),
  );
  const report = await runDaily(fakeEnv({ BUCKET: fakeBucket(statusText()) }), deps(fetch));
  assert.match(report.problems.join('\n'), /GitHub dispatch \(daily\) failed: HTTP 404/);
});
