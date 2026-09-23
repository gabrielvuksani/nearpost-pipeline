// Nearpost scheduler Worker: cron handlers only. There is deliberately no
// `fetch` handler, so the Worker has no public surface; monitoring is the
// nearpost-watchdog healthchecks.io ping.
// Wiring only; the logic lives in run.js and the pure modules it calls.
import { runTick, runDaily } from './run.js';

// Must match `[triggers] crons` in wrangler.toml (a test enforces this).
export const CRON_TICK = '*/5 * * * *';
export const CRON_DAILY = '0 6 * * *';

/** @returns {import('./run.js').Deps} */
function liveDeps() {
  // Wrap fetch rather than passing the global: an unbound fetch throws
  // "Illegal invocation" in Workers.
  return { fetch: (input, init) => fetch(input, init), now: () => Date.now() };
}

export default {
  /**
   * @param {{ cron: string }} controller
   * @param {import('./config.js').Env} env
   */
  async scheduled(controller, env) {
    switch (controller.cron) {
      case CRON_TICK:
        await runTick(env, liveDeps());
        return;
      case CRON_DAILY:
        await runDaily(env, liveDeps());
        return;
      default:
        throw new Error(`unknown cron ${JSON.stringify(controller.cron)}; expected "${CRON_TICK}" or "${CRON_DAILY}"`);
    }
  },
};
