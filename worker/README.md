# nearpost-scheduler (Cloudflare Worker)

This Worker drives and watches the Nearpost recording pipeline. It reads
`state/status.json` from R2. The format is defined in
[`../docs/status-contract.md`](../docs/status-contract.md).

- **Every 5 minutes (`*/5 * * * *`):** if a task has fallen due, it dispatches the
  GitHub workflow with `mode: tick`. It dispatches again when new work falls due, or
  when the last dispatch is 30 minutes old (a retry). The dispatch time is stored in
  KV under `last_dispatch:tick`.
- **Daily at 06:00 UTC (`0 6 * * *`):** it always dispatches `mode: daily`.
- **After either run:** it checks the watchdog rules and pings the healthchecks.io
  check `nearpost-watchdog`. When something is wrong it sends a `/fail` ping, with
  one problem per line.
- **No public surface:** the Worker has no `fetch` handler, and `workers_dev = false`
  means it has no URL at all. It is monitored only through the `nearpost-watchdog`
  ping.

Everything runs on free tiers. Worst case, KV takes one write per tick dispatch,
which is at most 288 a day against a free limit of 1,000. A tick uses well under 1 ms
of CPU.

## Develop

```sh
npm test            # node --test; no dependencies needed
npm ci              # installs the wrangler version pinned in package-lock.json
npm run dry-run     # wrangler deploy --dry-run (no login needed)
```

npm 11 may warn that install scripts for `esbuild`, `workerd` and `fsevents` were
not run. The warning is expected, and `wrangler deploy --dry-run` works without
approving them.

## One-time setup (Gabriel)

Run every command from this `worker/` directory, after `npm ci`. That way `npx
wrangler` uses the locally installed version pinned by `package-lock.json`.

```sh
cd pipeline/worker
npm ci
npx wrangler login
npx wrangler r2 bucket create nearpost-recorder   # skip if the bucket already exists
npx wrangler r2 bucket lock add nearpost-recorder ledger-blocks ledger/blocks/ --retention-indefinite
npx wrangler r2 bucket lock add nearpost-recorder snapshots snapshots/ --retention-days 400
npx wrangler kv namespace create STATE            # paste the printed id into wrangler.toml
npx wrangler secret put GITHUB_TOKEN
npx wrangler secret put HC_PING_KEY
npx wrangler deploy
```

To confirm the deploy works, check that the `nearpost-watchdog` check in healthchecks.io
turns green within about 5 minutes, which is one tick. If it turns red instead, the Worker is running
but reporting problems, and the ping body lists them. Before the pipeline's first
run, for example, it reports that `state/status.json` is missing.

- **Bucket locks:** objects under `ledger/blocks/` are kept forever, and objects under
  `snapshots/` for 400 days. While a lock applies, those objects cannot be deleted or
  overwritten.
- **`GITHUB_TOKEN`:** a **fine-grained personal access token**. Scope it to the
  `gabrielvuksani/nearpost-pipeline` repository only, with the single permission
  **"Actions: read and write"**.
  - **Expiry:** fine-grained tokens expire, so **track the expiry date** and rotate the
    token before it lapses. After it expires, every dispatch fails with HTTP 401, and
    the watchdog reports that.
  - **Where to keep it:** "Actions: read and write" also lets whoever holds the token
    **delete workflow runs, including their job summaries**. Keep the token **only in
    the Worker's secret store** (`wrangler secret put`). Don't put it in `.dev.vars`,
    shell history, CI variables or any other file. For local `wrangler dev`, use a
    separate short-lived token. `.dev.vars*` is already gitignored.
- **`HC_PING_KEY`:** the ping key from the healthchecks.io project settings. The first
  ping creates the check automatically (`?create=1`). After that, set its period to
  5 minutes and its grace time to about 15 minutes.
- **`record.yml`:** the workflow must exist on `main` and declare
  `on: workflow_dispatch` with a `mode` input that accepts `tick` and `daily`.
  Otherwise GitHub answers 422.

## Layout

| File | Role |
|---|---|
| `src/index.js` | `scheduled` handler (wiring only; no `fetch` handler by design) |
| `src/run.js` | tick and daily jobs |
| `src/decide.js` | `decideDispatch` (pure) |
| `src/health.js` | `assessHealth` (pure) |
| `src/status.js` | `parseStatus` validator (pure) |
| `src/github.js`, `src/healthchecks.js`, `src/http.js` | outbound HTTP; `fetch` is injected and secrets are redacted from errors |
| `src/storage.js` | R2 and KV access |
| `src/config.js` | required env vars and bindings |
