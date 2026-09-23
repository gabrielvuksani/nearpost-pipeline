// healthchecks.io ping client for the watchdog check.
import { request } from './http.js';

export const CHECK_SLUG = 'nearpost-watchdog';

/**
 * Report success, or failure with the problems as the ping body.
 * Never throws: a lost ping is itself what makes healthchecks.io alert.
 *
 * @param {{
 *   fetch: import('./http.js').FetchFn,
 *   pingKey: string,
 *   report: import('./health.js').HealthReport,
 * }} options
 * @returns {Promise<import('./http.js').CallResult>}
 */
export function pingHealthchecks({ fetch, pingKey, report }) {
  const base = `https://hc-ping.com/${pingKey}/${CHECK_SLUG}`;
  const context = { label: 'healthchecks ping', secrets: [pingKey] };
  if (report.ok) {
    return request(fetch, `${base}?create=1`, { method: 'GET' }, context);
  }
  const init = {
    method: 'POST',
    headers: { 'Content-Type': 'text/plain; charset=utf-8' },
    body: report.problems.join('\n'),
  };
  return request(fetch, `${base}/fail?create=1`, init, context);
}
