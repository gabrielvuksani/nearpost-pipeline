// Time constants and the ISO-8601 UTC format the status contract uses.

export const MINUTE_MS = 60_000;
export const HOUR_MS = 60 * MINUTE_MS;

const ISO_UTC = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$/;

/**
 * True for strings like `2026-10-10T11:30:00Z` (optional fractional seconds).
 * @param {unknown} value
 * @returns {value is string}
 */
export function isIsoUtc(value) {
  return typeof value === 'string' && ISO_UTC.test(value) && !Number.isNaN(Date.parse(value));
}

/**
 * Epoch milliseconds to the contract's format, without milliseconds.
 * @param {number} ms
 */
export function toIsoUtc(ms) {
  return new Date(ms).toISOString().replace(/\.\d{3}Z$/, 'Z');
}
