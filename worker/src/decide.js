// When should the tick workflow be dispatched? (docs/status-contract.md, "Worker rules")
import { MINUTE_MS } from './time.js';

export const RETRY_AFTER_MS = 30 * MINUTE_MS;

/**
 * Dispatch `tick` when some task is due and either new work fell due after the
 * last dispatch, or the last dispatch is old enough to warrant a retry.
 *
 * @param {import('./status.js').Status | null} status  null when unavailable
 * @param {number} now  epoch ms
 * @param {number | null} lastDispatchAt  epoch ms of the last tick dispatch
 * @returns {boolean}
 */
export function decideDispatch(status, now, lastDispatchAt) {
  if (!status) return false;
  const dueTimes = status.tasks.map((task) => Date.parse(task.due_at)).filter((due) => due <= now);
  if (dueTimes.length === 0) return false;
  if (lastDispatchAt === null) return true;
  const newWorkArrived = dueTimes.some((due) => due > lastDispatchAt);
  const retryDue = now - lastDispatchAt >= RETRY_AFTER_MS;
  return newWorkArrived || retryDue;
}
