import { test } from 'node:test';
import assert from 'node:assert/strict';
import { pingHealthchecks } from '../src/healthchecks.js';
import { fakeFetch, PING_KEY } from '../test-support/fakes.js';

const BASE = `https://hc-ping.com/${PING_KEY}/nearpost-watchdog`;

test('a healthy report pings the success URL', async () => {
  const fetch = fakeFetch();
  const result = await pingHealthchecks({ fetch, pingKey: PING_KEY, report: { ok: true, problems: [] } });
  assert.deepEqual(result, { ok: true });
  assert.equal(fetch.calls.length, 1);
  assert.equal(fetch.calls[0].url, `${BASE}?create=1`);
});

test('an unhealthy report POSTs the problems to the fail URL', async () => {
  const fetch = fakeFetch();
  const report = { ok: false, problems: ['first problem', 'second problem'] };
  const result = await pingHealthchecks({ fetch, pingKey: PING_KEY, report });
  assert.deepEqual(result, { ok: true });
  const [{ url, init }] = fetch.calls;
  assert.equal(url, `${BASE}/fail?create=1`);
  assert.equal(init.method, 'POST');
  assert.equal(init.body, 'first problem\nsecond problem');
  assert.match(init.headers['Content-Type'], /^text\/plain/);
});

test('a non-2xx ping response is an error with the status and no key', async () => {
  const fetch = fakeFetch(() => new Response(`rate limited ${PING_KEY}`, { status: 429 }));
  const result = await pingHealthchecks({ fetch, pingKey: PING_KEY, report: { ok: true, problems: [] } });
  assert.equal(result.ok, false);
  assert.match(result.error, /HTTP 429/);
  assert.ok(!result.error.includes(PING_KEY), result.error);
});

test('a network error resolves to an error (never rejects) without the key', async () => {
  const fetch = fakeFetch(() => {
    throw new TypeError(`fetch to ${BASE} failed`);
  });
  const result = await pingHealthchecks({ fetch, pingKey: PING_KEY, report: { ok: true, problems: [] } });
  assert.equal(result.ok, false);
  assert.match(result.error, /network error/);
  assert.ok(!result.error.includes(PING_KEY), result.error);
});
