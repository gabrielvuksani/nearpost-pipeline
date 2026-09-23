# nearpost-pipeline

The recording job for **Nearpost**. It builds an honest, append-only forecast ledger from
the 2026/27 Premier League onward:

- **Market snapshots:** The Odds API (free tier) and football-data.co.uk, captured at
  T-7d, T-24h and T-1h, plus our own closing line at T-15m.
- **FPL snapshots:** fixtures on every run, bootstrap-static daily, and `ep_next` frozen
  in the hour before each deadline.
- **Baseline forecasts:** Elo and Dixon-Coles, trained only on results from before the
  forecast. They are written before kickoff as hash-chained ledger entries. Dixon-Coles is
  our own numpy/scipy implementation, validated against penaltyblog in the tests.
  penaltyblog is a dev-only dependency, so it never runs with production secrets.
- **Settlement:** after each match, every forecast is scored with RPS, log loss and Brier.
  Scores are paired against our T-15m closing line and football-data.co.uk's closing
  lines.

This repository holds **code only**. Snapshots, the ledger and derived files live in a
private Cloudflare R2 bucket and are never committed. No Red-tier source (FotMob,
SofaScore, Understat, Opta) is used here.

## How it runs

```
Cloudflare Worker (worker/)                    GitHub Actions (.github/workflows/record.yml)
  */5 * * * *  read state/status.json ──due──▶  nearpost tick    capture / settle / ep_next
  0 6 * * *    dispatch daily ─────────────────▶ nearpost daily   refresh, benchmark, verify, scoreboard, tick
  every tick   watchdog → healthchecks.io                  │
                                                           ▼
                                              R2: snapshots/  ledger/blocks/  state/  derived/
```

- **Dispatch:** the Worker triggers runs with `workflow_dispatch`. GitHub's own
  `schedule` is only a daily backup, because it can be delayed, dropped, or disabled
  after 60 idle days.
- **Health checks:** every run pings healthchecks.io (`nearpost-tick`,
  `nearpost-daily`). The Worker's `nearpost-watchdog` check raises a separate alert
  when work goes overdue, when a capture window closes without a capture, when the
  daily run is stale, when Odds API credits run low, or when the Worker itself stops.
- **Failures are loud:** a failing source leaves its work pending, so the next run
  retries it. The run then exits non-zero and pings `/fail` with the reason and a link
  to the run.

## The ledger

- **Blocks:** each run that records anything writes one block,
  `ledger/blocks/NNNNNN.json`, created with `If-None-Match: *`. No code path can
  overwrite a block, and two runs can never claim the same number.
- **Hash chain:** every entry commits to the previous entry's hash (SHA-256 over
  canonical JSON), so editing, reordering or deleting any entry breaks the chain.
- **Verification:** `daily` re-verifies the whole chain from genesis before it appends
  anything. It publishes the head hash in the public Actions job summary.
- **Entry kinds:** `forecast`, `settlement`, `benchmark`, `fpl-ep-next` and
  `fpl-result`.
- **Unavailable forecasts:** a forecast the market couldn't price is recorded as
  unavailable, with a reason. A forecast that is never made shows up as *missed* on the
  watchdog.
- **Kickoff guard:** a forecast cannot be written at or after kickoff. The check runs
  against the freshest FPL kickoff time, not the one known when the task was planned.

`ledger/index.json` is a self-healing cache (what's done, plus open forecasts). It can
always be rebuilt from the blocks. Each run checks its head against the last block before
chaining onto it.

### What the ledger does and doesn't prove

- **Tamper-evident:** any edit, reorder or deletion breaks the hash chain, and `verify`
  finds it.
- **Write-once against the pipeline's own credentials:** with the R2 bucket lock on
  `ledger/blocks/`, the Actions R2 token (or a compromised dependency running with it)
  cannot delete or overwrite a block.
- **Not proof against the account owner:** whoever owns the Cloudflare account can remove
  a lock rule and rewrite the whole chain consistently. The chain is unkeyed SHA-256.
- **Timestamps are claimed, not attested:** `issued_at` and `recorded_at` are written by
  the pipeline. The public job summary records the head hash on GitHub. But runs can be
  deleted by the repo owner (or anyone holding the Worker's Actions token), and GitHub
  keeps public-repo runs for at most 90 days.
- **Planned (step 1):** anchor the head hash in an append-only public log the owner can't
  rewrite (Sigstore/Rekor via `actions/attest`, or OpenTimestamps). Also compare each
  block's server-set R2 `LastModified` against its claimed times in `verify`. Until then,
  the honest claim is: tamper-evident, write-once against CI credentials, and self-attested
  in time.

## Develop

```sh
uv sync
uv run pytest                     # offline: synthetic data only, no network
uv run ruff check src tests && uv run ruff format --check src tests
(cd worker && node --test)

uv run nearpost preview           # fit on live data, print the next fixtures; writes no ledger
uv run nearpost daily             # full run into ./.nearpost-data (no secrets needed locally)
uv run nearpost verify            # verify the whole chain
```

## Go-live

Nothing here has been done yet. Every step needs your accounts or approval.

1. **Push this repository to GitHub.** The workflows must be on `main`. `record.yml`
   starts disabled, so its backup schedule can't fail before secrets exist. The wizard
   enables it.
2. **Fill in credentials:**
   ```sh
   cp .env.example .env && chmod 600 .env
   ```
   Fill in whatever you already have; blanks are fine. `.env` is gitignored.
3. **Run the wizard:**
   ```sh
   ./scripts/go-live.sh
   ```
   - It offers each value from `.env`, checks it against the real service, and pushes
     it to GitHub Actions secrets or the Worker's secret store. Secrets travel only over
     stdin or environment variables.
   - Where only you can act, it opens the right page and says exactly what to do:
     signups, the R2 API token, the GitHub token, and healthchecks.io schedules and
     alerts.
   - It creates the R2 bucket, its write-once locks and the KV namespace, deploys the
     Worker, and starts the first `daily` run. Each of those asks for confirmation first.
   - It is safe to re-run.

What the wizard sets up:

- **The Odds API:** the free Starter key (500 credits/month). Requests use
  `regions=eu` and `markets=h2h,totals`, costing 2 credits per capture. At about 7–8
  kickoff slots × 4 horizons per gameweek, that is roughly 200–300 credits a month. A
  reserve guard protects the near-kickoff captures.
- **Cloudflare:**
  - the R2 bucket `nearpost-recorder`;
  - bucket locks: `ledger/blocks/` kept indefinitely, `snapshots/` kept 400 days;
  - an R2 token scoped to that bucket;
  - the `nearpost-scheduler` Worker, with no public URL.
- **healthchecks.io:** the checks `nearpost-daily` (1 day / 3 h grace),
  `nearpost-watchdog` (5 min / 15 min) and `nearpost-tick` (7 days), with phone alerts.
- **GitHub:**
  - Actions secrets: `ODDS_API_KEY`, `HEALTHCHECKS_PING_KEY`, `R2_ACCOUNT_ID`,
    `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET`.
  - A fine-grained token for the Worker, scoped to this repo with **Actions: read and
    write** only. Note its expiry date: when it expires, recording stops.

**Timing:** GW6 T-7d captures start **2026-10-03 11:30 UTC**, and the GW6 deadline
(ep_next freeze) is **2026-10-10 10:00 UTC**. Going live by 2026-10-02 means the first
gameweek is recorded at every horizon.

## Layout

| Path | What |
|---|---|
| `src/nearpost/sources/` | FPL, football-data.co.uk and The Odds API parsers, plus fetch-and-archive |
| `src/nearpost/models/` | Elo (salvaged), Dixon-Coles (numpy/scipy MLE with analytic gradient), leak-safe training set |
| `src/nearpost/ledger/` | hash chain, block repository, self-healing index |
| `src/nearpost/records/` | forecast, settlement and benchmark entry builders |
| `src/nearpost/jobs/` | `tick`, `daily`, `preview`, status and the runner |
| `src/nearpost/tasks.py`, `horizons.py` | what is due, and when each horizon's window opens and closes |
| `docs/status-contract.md` | the pipeline ↔ Worker contract |
| `worker/` | Cloudflare scheduler and watchdog (no public surface) |
| `scripts/go-live.sh`, `.env.example` | one-time go-live wizard and its credentials template |

## License

No license is granted. The code is published for transparency; all rights reserved.
