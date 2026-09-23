// Validation of `state/status.json` (see docs/status-contract.md).
import { isIsoUtc } from './time.js';

export const SCHEMA_VERSION = 1;

/**
 * @typedef {{ kind: string, due_at: string, match_id?: string, horizon?: string,
 *   kickoff?: string, gameweek?: number }} Task
 * @typedef {{ kind: string, window_closed_at: string, match_id?: string,
 *   horizon?: string, gameweek?: number }} MissedEntry
 * @typedef {{
 *   schema: 1,
 *   generated_at: string,
 *   last_success: { daily?: string | null, tick?: string | null },
 *   tasks: Task[],
 *   missed: MissedEntry[],
 *   odds_api: { credits_remaining: number, observed_at: string } | null,
 * }} Status
 * @typedef {{ status: Status, error?: undefined } | { error: string, status?: undefined }} StatusResult
 */

/**
 * Parse and validate the raw text of status.json. Never throws.
 * @param {string} text
 * @returns {StatusResult}
 */
export function parseStatus(text) {
  let value;
  try {
    value = JSON.parse(text);
  } catch (error) {
    return { error: `status.json is not valid JSON: ${error.message}` };
  }
  const problem = findShapeProblem(value);
  return problem ? { error: `status.json is invalid: ${problem}` } : { status: value };
}

/** @param {unknown} value @returns {value is Record<string, any>} */
const isObject = (value) => typeof value === 'object' && value !== null && !Array.isArray(value);

/**
 * First contract violation found, or null when the shape is valid.
 * @param {unknown} value
 * @returns {string | null}
 */
function findShapeProblem(value) {
  if (!isObject(value)) return 'top level must be a JSON object';
  if (value.schema !== SCHEMA_VERSION) {
    return `unknown schema ${JSON.stringify(value.schema)} (expected ${SCHEMA_VERSION})`;
  }
  if (!isIsoUtc(value.generated_at)) return 'generated_at must be an ISO-8601 UTC timestamp';
  return (
    lastSuccessProblem(value.last_success) ??
    listProblem(value.tasks, 'tasks', 'due_at') ??
    listProblem(value.missed, 'missed', 'window_closed_at') ??
    oddsApiProblem(value.odds_api)
  );
}

/** @param {unknown} lastSuccess */
function lastSuccessProblem(lastSuccess) {
  if (!isObject(lastSuccess)) return 'last_success must be an object';
  for (const mode of ['daily', 'tick']) {
    const stamp = lastSuccess[mode];
    if (stamp != null && !isIsoUtc(stamp)) {
      return `last_success.${mode} must be an ISO-8601 UTC timestamp or absent`;
    }
  }
  return null;
}

/**
 * @param {unknown} list
 * @param {string} name
 * @param {string} timeField
 */
function listProblem(list, name, timeField) {
  if (!Array.isArray(list)) return `${name} must be an array`;
  for (const [index, entry] of list.entries()) {
    const where = `${name}[${index}]`;
    if (!isObject(entry)) return `${where} must be an object`;
    if (typeof entry.kind !== 'string') return `${where}.kind must be a string`;
    if (!isIsoUtc(entry[timeField])) return `${where}.${timeField} must be an ISO-8601 UTC timestamp`;
  }
  return null;
}

/** @param {unknown} oddsApi */
function oddsApiProblem(oddsApi) {
  if (oddsApi === null) return null;
  if (!isObject(oddsApi)) return 'odds_api must be an object or null';
  if (!Number.isFinite(oddsApi.credits_remaining)) return 'odds_api.credits_remaining must be a number';
  if (!isIsoUtc(oddsApi.observed_at)) return 'odds_api.observed_at must be an ISO-8601 UTC timestamp';
  return null;
}
