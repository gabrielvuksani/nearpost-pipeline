// Reads and writes against the R2 (BUCKET) and KV (STATE) bindings.
// Failures come back as values so the watchdog can report them.
import { parseStatus } from './status.js';
import { describeError } from './http.js';
import { isIsoUtc, toIsoUtc } from './time.js';

export const STATUS_KEY = 'state/status.json';
export const LAST_TICK_KEY = 'last_dispatch:tick';

/**
 * @param {NonNullable<import('./config.js').Env['BUCKET']>} bucket
 * @returns {Promise<import('./status.js').StatusResult>}
 */
export async function loadStatus(bucket) {
  try {
    const object = await bucket.get(STATUS_KEY);
    if (object === null) return { error: `${STATUS_KEY} is missing from R2` };
    return parseStatus(await object.text());
  } catch (error) {
    return { error: `could not read ${STATUS_KEY} from R2: ${describeError(error)}` };
  }
}

/**
 * Last tick dispatch time. Unreadable or corrupt values count as "never",
 * which errs towards dispatching, and are reported as a problem.
 *
 * @param {NonNullable<import('./config.js').Env['STATE']>} kv
 * @returns {Promise<{ at: number | null, problem: string | null }>}
 */
export async function loadLastTickDispatch(kv) {
  let value;
  try {
    value = await kv.get(LAST_TICK_KEY);
  } catch (error) {
    return { at: null, problem: `could not read KV ${LAST_TICK_KEY}: ${describeError(error)}` };
  }
  if (value === null) return { at: null, problem: null };
  if (!isIsoUtc(value)) {
    return { at: null, problem: `KV ${LAST_TICK_KEY} holds an invalid timestamp: ${JSON.stringify(value)}` };
  }
  return { at: Date.parse(value), problem: null };
}

/**
 * @param {NonNullable<import('./config.js').Env['STATE']>} kv
 * @param {number} at  epoch ms
 * @returns {Promise<string | null>}  a problem description on failure
 */
export async function recordTickDispatch(kv, at) {
  try {
    await kv.put(LAST_TICK_KEY, toIsoUtc(at));
    return null;
  } catch (error) {
    return `could not record tick dispatch in KV ${LAST_TICK_KEY}: ${describeError(error)}`;
  }
}
