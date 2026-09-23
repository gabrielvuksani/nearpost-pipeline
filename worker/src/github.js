// GitHub Actions `workflow_dispatch` client.
import { request } from './http.js';

const USER_AGENT = 'nearpost-scheduler (Cloudflare Worker)';

/**
 * Trigger the recording workflow. Any 2xx (GitHub answers 204) is success.
 *
 * @param {{
 *   fetch: import('./http.js').FetchFn,
 *   repo: string,          // "owner/name"
 *   workflowFile: string,  // e.g. "record.yml"
 *   token: string,
 *   mode: 'tick' | 'daily',
 *   ref?: string,
 * }} options
 * @returns {Promise<import('./http.js').CallResult>}
 */
export function dispatchWorkflow({ fetch, repo, workflowFile, token, mode, ref = 'main' }) {
  const url =
    `https://api.github.com/repos/${repo}/actions/workflows/` +
    `${encodeURIComponent(workflowFile)}/dispatches`;
  const init = {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${token}`,
      Accept: 'application/vnd.github+json',
      'X-GitHub-Api-Version': '2022-11-28',
      'Content-Type': 'application/json',
      'User-Agent': USER_AGENT,
    },
    body: JSON.stringify({ ref, inputs: { mode } }),
  };
  return request(fetch, url, init, { label: `GitHub dispatch (${mode})`, secrets: [token] });
}
