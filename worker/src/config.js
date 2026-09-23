// Required Worker configuration: vars, secrets and bindings.

export const REQUIRED_CONFIG = Object.freeze([
  'GITHUB_REPO',
  'WORKFLOW_FILE',
  'GITHUB_TOKEN',
  'HC_PING_KEY',
  'BUCKET',
  'STATE',
]);

/**
 * @typedef {{
 *   GITHUB_REPO?: string, WORKFLOW_FILE?: string,
 *   GITHUB_TOKEN?: string, HC_PING_KEY?: string,
 *   BUCKET?: { get(key: string): Promise<{ text(): Promise<string> } | null> },
 *   STATE?: { get(key: string): Promise<string | null>, put(key: string, value: string): Promise<void> },
 * }} Env
 */

/**
 * Names of required settings that are absent or blank. Never returns values.
 * @param {Env} env
 * @returns {string[]}
 */
export function findMissingConfig(env) {
  return REQUIRED_CONFIG.filter((name) => {
    const value = env[name];
    return value == null || (typeof value === 'string' && value.trim() === '');
  });
}
