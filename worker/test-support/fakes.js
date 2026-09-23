// Test doubles for Worker bindings and fetch. They record calls on purpose.

/** R2 binding whose single object is `text` (null means "object missing"). */
export function fakeBucket(text) {
  const reads = [];
  return {
    reads,
    async get(key) {
      reads.push(key);
      return text == null ? null : { text: async () => text };
    },
  };
}

export function throwingBucket(message) {
  return {
    async get() {
      throw new Error(message);
    },
  };
}

/** KV binding backed by a Map. */
export function fakeKv(initial = {}) {
  const store = new Map(Object.entries(initial));
  return {
    store,
    async get(key) {
      return store.has(key) ? store.get(key) : null;
    },
    async put(key, value) {
      store.set(key, value);
    },
  };
}

/**
 * fetch double. `respond(url, init)` returns a Response or throws.
 * Defaults to 204 for GitHub and 200 for everything else.
 */
export function fakeFetch(respond = defaultResponder) {
  const calls = [];
  const fn = async (url, init = {}) => {
    calls.push({ url: String(url), init });
    return respond(String(url), init);
  };
  fn.calls = calls;
  return fn;
}

function defaultResponder(url) {
  return url.startsWith('https://api.github.com/')
    ? new Response(null, { status: 204 })
    : new Response('OK', { status: 200 });
}

export const TOKEN = 'github_pat_SECRET_TOKEN_123';
export const PING_KEY = 'SECRET_PING_KEY_456';

export function fakeEnv(overrides = {}) {
  return {
    GITHUB_REPO: 'gabrielvuksani/nearpost-pipeline',
    WORKFLOW_FILE: 'record.yml',
    GITHUB_TOKEN: TOKEN,
    HC_PING_KEY: PING_KEY,
    BUCKET: fakeBucket(null),
    STATE: fakeKv(),
    ...overrides,
  };
}
