// Shared builders for tests. Everything returned is deep-frozen so any
// accidental mutation inside the code under test throws a TypeError.

export const MINUTE = 60_000;
export const HOUR = 60 * MINUTE;
export const NOW = Date.parse('2026-10-10T12:00:00Z');

/** @param {number} ms */
export const iso = (ms) => new Date(ms).toISOString().replace('.000Z', 'Z');

/** @template T @param {T} value @returns {T} */
export function deepFreeze(value) {
  if (value && typeof value === 'object') {
    Object.values(value).forEach(deepFreeze);
    Object.freeze(value);
  }
  return value;
}

/** A status that passes every health rule at NOW. */
export function healthyStatus(overrides = {}) {
  return deepFreeze({
    schema: 1,
    generated_at: iso(NOW - 5 * MINUTE),
    last_success: { daily: iso(NOW - 6 * HOUR), tick: iso(NOW - 5 * MINUTE) },
    tasks: [],
    missed: [],
    odds_api: { credits_remaining: 431, observed_at: iso(NOW - HOUR) },
    ...overrides,
  });
}

export function captureTask(dueAt, overrides = {}) {
  return {
    kind: 'capture',
    due_at: iso(dueAt),
    match_id: '2026-27:arsenal-v-chelsea',
    horizon: 'T-24h',
    kickoff: iso(dueAt + 24 * HOUR),
    ...overrides,
  };
}

export function missedCapture(closedAt) {
  return {
    kind: 'capture',
    match_id: '2026-27:fulham-v-hull-city',
    horizon: 'T-1h',
    window_closed_at: iso(closedAt),
  };
}
