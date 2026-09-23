// The two Worker jobs: tick and daily.
// Side effects arrive through `env` (bindings) and `deps` (fetch, clock).
import { findMissingConfig } from './config.js';
import { decideDispatch } from './decide.js';
import { assessHealth } from './health.js';
import { dispatchWorkflow } from './github.js';
import { pingHealthchecks } from './healthchecks.js';
import { loadStatus, loadLastTickDispatch, recordTickDispatch } from './storage.js';

export { LAST_TICK_KEY } from './storage.js';

/**
 * @typedef {import('./config.js').Env} Env
 * @typedef {import('./health.js').HealthReport} HealthReport
 * @typedef {{ fetch: import('./http.js').FetchFn, now: () => number }} Deps
 */

const GITHUB_CONFIG = ['GITHUB_REPO', 'WORKFLOW_FILE', 'GITHUB_TOKEN'];

/**
 * Every 5 minutes: dispatch `tick` if work is due, then report health.
 * @param {Env} env @param {Deps} deps
 * @returns {Promise<HealthReport>}
 */
export async function runTick(env, deps) {
  const now = deps.now();
  const missing = findMissingConfig(env);
  const statusResult = await readStatus(env);
  const last = env.STATE ? await loadLastTickDispatch(env.STATE) : { at: null, problem: null };

  let dispatchError = null;
  let recordProblem = null;
  if (decideDispatch(statusResult.status ?? null, now, last.at)) {
    const outcome = await dispatch(env, deps, 'tick', missing);
    if (!outcome.ok) dispatchError = outcome.error;
    else if (env.STATE) recordProblem = await recordTickDispatch(env.STATE, now);
  }

  const report = combine(
    configProblems(missing),
    [last.problem, recordProblem].filter((problem) => problem !== null),
    assessHealth(statusResult, now, dispatchError),
  );
  await publish(env, deps, 'tick', report, missing);
  return report;
}

/**
 * Daily at 06:00 UTC: dispatch `daily` unconditionally, then report health.
 * @param {Env} env @param {Deps} deps
 * @returns {Promise<HealthReport>}
 */
export async function runDaily(env, deps) {
  const missing = findMissingConfig(env);
  const outcome = await dispatch(env, deps, 'daily', missing);
  const statusResult = await readStatus(env);
  const report = combine(
    configProblems(missing),
    [],
    assessHealth(statusResult, deps.now(), outcome.ok ? null : outcome.error),
  );
  await publish(env, deps, 'daily', report, missing);
  return report;
}

/** @param {Env} env */
function readStatus(env) {
  return env.BUCKET
    ? loadStatus(env.BUCKET)
    : Promise.resolve({ error: 'R2 binding BUCKET is not configured' });
}

/**
 * @param {Env} env @param {Deps} deps
 * @param {'tick' | 'daily'} mode
 * @param {string[]} missing
 * @returns {Promise<import('./http.js').CallResult>}
 */
function dispatch(env, deps, mode, missing) {
  const missingGithub = missing.filter((name) => GITHUB_CONFIG.includes(name));
  if (missingGithub.length > 0) {
    return Promise.resolve({
      ok: false,
      error: `${mode} dispatch needed but skipped: missing ${missingGithub.join(', ')}`,
    });
  }
  return dispatchWorkflow({
    fetch: deps.fetch,
    repo: env.GITHUB_REPO,
    workflowFile: env.WORKFLOW_FILE,
    token: env.GITHUB_TOKEN,
    mode,
  });
}

/** @param {string[]} missing */
const configProblems = (missing) =>
  missing.length > 0 ? [`missing configuration: ${missing.join(', ')}`] : [];

/**
 * @param {string[]} configIssues @param {string[]} stateIssues @param {HealthReport} health
 * @returns {HealthReport}
 */
function combine(configIssues, stateIssues, health) {
  const problems = [...configIssues, ...stateIssues, ...health.problems];
  return { ok: problems.length === 0, problems };
}

/**
 * Log the outcome and ping healthchecks.io. Never throws: if the ping is lost,
 * healthchecks.io's own missed-ping alert fires.
 *
 * @param {Env} env @param {Deps} deps @param {string} job
 * @param {HealthReport} report @param {string[]} missing
 */
async function publish(env, deps, job, report, missing) {
  if (report.ok) console.log(`[${job}] healthy`);
  else console.error(`[${job}] ${report.problems.length} problem(s):\n${report.problems.join('\n')}`);

  if (missing.includes('HC_PING_KEY')) {
    console.error(`[${job}] cannot ping healthchecks: HC_PING_KEY is not configured`);
    return;
  }
  const result = await pingHealthchecks({ fetch: deps.fetch, pingKey: env.HC_PING_KEY, report });
  if (!result.ok) console.error(`[${job}] ${result.error}`);
}
