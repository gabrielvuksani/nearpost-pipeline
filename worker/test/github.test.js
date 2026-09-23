import { test } from 'node:test';
import assert from 'node:assert/strict';
import { dispatchWorkflow } from '../src/github.js';
import { fakeFetch, TOKEN } from '../test-support/fakes.js';

const call = (fetch, mode = 'tick') =>
  dispatchWorkflow({
    fetch,
    repo: 'gabrielvuksani/nearpost-pipeline',
    workflowFile: 'record.yml',
    token: TOKEN,
    mode,
  });

test('posts a workflow_dispatch with the documented URL, headers and body', async () => {
  const fetch = fakeFetch();
  const result = await call(fetch, 'tick');

  assert.deepEqual(result, { ok: true });
  assert.equal(fetch.calls.length, 1);
  const [{ url, init }] = fetch.calls;
  assert.equal(
    url,
    'https://api.github.com/repos/gabrielvuksani/nearpost-pipeline/actions/workflows/record.yml/dispatches',
  );
  assert.equal(init.method, 'POST');
  assert.equal(init.headers.Authorization, `Bearer ${TOKEN}`);
  assert.equal(init.headers.Accept, 'application/vnd.github+json');
  assert.equal(init.headers['X-GitHub-Api-Version'], '2022-11-28');
  assert.equal(init.headers['Content-Type'], 'application/json');
  assert.ok(init.headers['User-Agent']);
  assert.deepEqual(JSON.parse(init.body), { ref: 'main', inputs: { mode: 'tick' } });
});

test('daily mode goes in the inputs', async () => {
  const fetch = fakeFetch();
  await call(fetch, 'daily');
  assert.deepEqual(JSON.parse(fetch.calls[0].init.body).inputs, { mode: 'daily' });
});

test('non-2xx becomes an error with the status code and no token', async () => {
  const fetch = fakeFetch(
    () => new Response(`{"message":"Bad credentials ${TOKEN}"}`, { status: 401, statusText: 'Unauthorized' }),
  );
  const result = await call(fetch);
  assert.equal(result.ok, false);
  assert.match(result.error, /HTTP 401/);
  assert.match(result.error, /Bad credentials/);
  assert.ok(!result.error.includes(TOKEN), result.error);
});

test('a 200 without 204 still counts as success (any 2xx)', async () => {
  const result = await call(fakeFetch(() => new Response('{}', { status: 200 })));
  assert.deepEqual(result, { ok: true });
});

test('long error bodies are truncated', async () => {
  const fetch = fakeFetch(() => new Response('x'.repeat(5000), { status: 500 }));
  const result = await call(fetch);
  assert.ok(result.error.length < 400, `length ${result.error.length}`);
});

test('a network error becomes an error without the token', async () => {
  const fetch = fakeFetch(() => {
    throw new TypeError(`connect failed with Bearer ${TOKEN}`);
  });
  const result = await call(fetch);
  assert.equal(result.ok, false);
  assert.match(result.error, /network error/);
  assert.ok(!result.error.includes(TOKEN), result.error);
});
