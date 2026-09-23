// Small helpers shared by the outbound HTTP clients.

/** @typedef {(input: string, init?: RequestInit) => Promise<Response>} FetchFn */
/** @typedef {{ ok: true } | { ok: false, error: string }} CallResult */

export const REQUEST_TIMEOUT_MS = 10_000;
const MAX_BODY_CHARS = 200;

/**
 * Replace every occurrence of each secret with `[redacted]`.
 * @param {string} text
 * @param {Array<string | undefined>} secrets
 */
export function redact(text, secrets) {
  return secrets
    .filter((secret) => typeof secret === 'string' && secret.length > 0)
    .reduce((out, secret) => out.split(secret).join('[redacted]'), text);
}

/** @param {unknown} error */
export function describeError(error) {
  return error instanceof Error ? `${error.name}: ${error.message}` : String(error);
}

/**
 * Status line plus a truncated body, for error messages.
 * @param {Response} response
 */
export async function describeResponse(response) {
  const statusLine = `HTTP ${response.status}${response.statusText ? ` ${response.statusText}` : ''}`;
  let body;
  try {
    body = (await response.text()).trim();
  } catch (error) {
    return `${statusLine} (body unreadable: ${describeError(error)})`;
  }
  if (!body) return statusLine;
  const snippet = body.length > MAX_BODY_CHARS ? `${body.slice(0, MAX_BODY_CHARS)}…` : body;
  return `${statusLine}: ${snippet}`;
}

/**
 * Perform a request and fold every failure into a `CallResult`; never throws.
 * `secrets` are scrubbed from any error text.
 *
 * @param {FetchFn} fetch
 * @param {string} url
 * @param {RequestInit} init
 * @param {{ label: string, secrets: Array<string | undefined> }} context
 * @returns {Promise<CallResult>}
 */
export async function request(fetch, url, init, { label, secrets }) {
  let response;
  try {
    response = await fetch(url, { ...init, signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS) });
  } catch (error) {
    return { ok: false, error: redact(`${label} network error: ${describeError(error)}`, secrets) };
  }
  if (response.ok) return { ok: true };
  const detail = await describeResponse(response);
  return { ok: false, error: redact(`${label} failed: ${detail}`, secrets) };
}
