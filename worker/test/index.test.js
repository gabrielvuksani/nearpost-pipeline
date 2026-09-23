import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import worker, { CRON_TICK, CRON_DAILY } from '../src/index.js';
import { healthyStatus } from '../test-support/fixtures.js';
import { fakeBucket, fakeEnv, fakeFetch } from '../test-support/fakes.js';

test('the Worker has no public surface: it exports only a scheduled handler', () => {
  assert.deepEqual(Object.keys(worker), ['scheduled']);
  assert.equal(worker.fetch, undefined);
});

test('scheduled routes the tick cron to the tick job', async (t) => {
  t.mock.method(console, 'log', () => {});
  t.mock.method(console, 'error', () => {});
  const fetch = fakeFetch();
  t.mock.method(globalThis, 'fetch', fetch);
  const now = Date.now();
  const status = healthyStatus({
    generated_at: new Date(now).toISOString(),
    tasks: [{ kind: 'settle', due_at: new Date(now - 60_000).toISOString() }],
  });

  await worker.scheduled({ cron: CRON_TICK }, fakeEnv({ BUCKET: fakeBucket(JSON.stringify(status)) }), {});

  const body = JSON.parse(fetch.calls.find((c) => c.url.includes('api.github.com')).init.body);
  assert.equal(body.inputs.mode, 'tick');
});

test('scheduled routes the daily cron to the daily job', async (t) => {
  t.mock.method(console, 'log', () => {});
  t.mock.method(console, 'error', () => {});
  const fetch = fakeFetch();
  t.mock.method(globalThis, 'fetch', fetch);

  await worker.scheduled({ cron: CRON_DAILY }, fakeEnv(), {});

  const body = JSON.parse(fetch.calls.find((c) => c.url.includes('api.github.com')).init.body);
  assert.equal(body.inputs.mode, 'daily');
});

test('scheduled rejects an unknown cron loudly', async (t) => {
  t.mock.method(console, 'error', () => {});
  await assert.rejects(worker.scheduled({ cron: '* * * * *' }, fakeEnv(), {}), /unknown cron/);
});

test('wrangler.toml declares exactly the crons the Worker handles', async () => {
  const toml = await readFile(new URL('../wrangler.toml', import.meta.url), 'utf8');
  const line = toml.split('\n').find((l) => /^\s*crons\s*=/.test(l));
  assert.ok(line, 'crons line present');
  const crons = JSON.parse(line.split('=')[1].trim());
  assert.deepEqual(crons, [CRON_TICK, CRON_DAILY]);
});

test('wrangler.toml disables workers.dev and declares no routes', async () => {
  const toml = await readFile(new URL('../wrangler.toml', import.meta.url), 'utf8');
  const lines = toml.split('\n').map((l) => l.replace(/#.*/, '').trim());
  assert.ok(lines.includes('workers_dev = false'), 'workers_dev = false present');
  assert.ok(!lines.some((l) => /^(routes?\s*=|\[\[?routes?\]\]?)/.test(l)), 'no routes declared');
});
