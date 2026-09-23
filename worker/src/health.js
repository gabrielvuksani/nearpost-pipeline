// Watchdog rules (docs/status-contract.md, "Report a problem").
import { HOUR_MS, MINUTE_MS } from './time.js';

export const STALE_AFTER_MS = 26 * HOUR_MS;
export const OVERDUE_AFTER_MS = 40 * MINUTE_MS;
export const MISSED_ALERT_WINDOW_MS = 24 * HOUR_MS;
export const MIN_ODDS_CREDITS = 25;

/** @typedef {{ ok: boolean, problems: string[] }} HealthReport */

/**
 * @param {import('./status.js').StatusResult} statusResult  output of parseStatus, or an `{error}` from loading
 * @param {number} now  epoch ms
 * @param {string | null} dispatchError  description of a failed GitHub dispatch, if any
 * @returns {HealthReport}
 */
export function assessHealth(statusResult, now, dispatchError) {
  const statusProblems = statusResult.status
    ? statusRuleProblems(statusResult.status, now)
    : [`status.json unusable: ${statusResult.error}`];
  const problems = dispatchError
    ? [...statusProblems, `GitHub dispatch failed: ${dispatchError}`]
    : statusProblems;
  return { ok: problems.length === 0, problems };
}

/**
 * @param {import('./status.js').Status} status
 * @param {number} now
 * @returns {string[]}
 */
function statusRuleProblems(status, now) {
  return [
    ...staleness('generated_at', status.generated_at, now),
    ...dailySuccessProblems(status.last_success.daily, now),
    ...status.tasks.flatMap((task) => overdueProblems(task, now)),
    ...status.missed.flatMap((entry) => missedProblems(entry, now)),
    ...oddsProblems(status.odds_api),
  ];
}

const hoursAgo = (ms) => `${(ms / HOUR_MS).toFixed(1)}h ago`;

/** @param {string} label @param {string} stamp @param {number} now */
function staleness(label, stamp, now) {
  const age = now - Date.parse(stamp);
  return age > STALE_AFTER_MS ? [`${label} ${stamp} is stale (${hoursAgo(age)}, limit 26h)`] : [];
}

/** @param {string | null | undefined} daily @param {number} now */
function dailySuccessProblems(daily, now) {
  return daily == null ? ['last_success.daily is missing'] : staleness('last_success.daily', daily, now);
}

/** @param {import('./status.js').Task} task @param {number} now */
function overdueProblems(task, now) {
  const late = now - Date.parse(task.due_at);
  if (late <= OVERDUE_AFTER_MS) return [];
  const minutes = Math.floor(late / MINUTE_MS);
  return [`overdue task: ${describe(task)} was due ${task.due_at} (${minutes} min ago, limit 40 min)`];
}

/** @param {import('./status.js').MissedEntry} entry @param {number} now */
function missedProblems(entry, now) {
  const sinceClosed = now - Date.parse(entry.window_closed_at);
  return sinceClosed <= MISSED_ALERT_WINDOW_MS
    ? [`missed task: ${describe(entry)} window closed ${entry.window_closed_at}`]
    : [];
}

/** @param {import('./status.js').Status['odds_api']} oddsApi */
function oddsProblems(oddsApi) {
  if (oddsApi === null || oddsApi.credits_remaining >= MIN_ODDS_CREDITS) return [];
  return [`odds API credits low: ${oddsApi.credits_remaining} remaining (threshold ${MIN_ODDS_CREDITS})`];
}

/** e.g. `capture 2026-27:arsenal-v-chelsea T-24h` or `fpl-deadline GW6`. */
function describe({ kind, match_id, horizon, gameweek }) {
  const parts = [kind, match_id, horizon, gameweek == null ? undefined : `GW${gameweek}`];
  return parts.filter((part) => part != null).join(' ');
}
