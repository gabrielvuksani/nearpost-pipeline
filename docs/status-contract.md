# `state/status.json`: the pipeline ↔ Worker contract

The Python pipeline rewrites this object in R2 at the end of **every** run, even a failed one if it gets that far.
The Cloudflare Worker reads it through its R2 binding every five minutes. It uses the file for two things:

1. **Dispatch:** trigger a `tick` run when new work has fallen due.
2. **Watchdog:** decide whether the recording job is healthy, and report that to healthchecks.io.

All timestamps are UTC ISO-8601 strings with a `Z` suffix, e.g. `2026-10-10T11:30:00Z`.

```json
{
  "schema": 1,
  "generated_at": "2026-10-09T06:02:11Z",
  "last_success": {
    "daily": "2026-10-09T06:02:11Z",
    "tick": "2026-10-08T19:45:40Z"
  },
  "tasks": [
    {
      "kind": "capture",
      "due_at": "2026-10-09T11:30:00Z",
      "match_id": "2026-27:arsenal-v-chelsea",
      "horizon": "T-24h",
      "kickoff": "2026-10-10T11:30:00Z"
    },
    {
      "kind": "settle",
      "due_at": "2026-10-10T13:30:00Z",
      "match_id": "2026-27:liverpool-v-everton",
      "kickoff": "2026-10-10T11:30:00Z"
    },
    {
      "kind": "fpl-deadline",
      "due_at": "2026-10-10T09:00:00Z",
      "gameweek": 6
    }
  ],
  "missed": [
    {
      "kind": "capture",
      "match_id": "2026-27:fulham-v-hull-city",
      "horizon": "T-1h",
      "window_closed_at": "2026-10-10T13:45:00Z"
    }
  ],
  "odds_api": {
    "credits_remaining": 431,
    "observed_at": "2026-10-08T19:45:38Z"
  }
}
```

## Field semantics

| Field | Meaning |
|---|---|
| `schema` | Contract version. The Worker must treat an unknown version as a problem. |
| `generated_at` | When this file was written. |
| `last_success.<mode>` | End time of the last run of that mode (`daily`, `tick`) that finished without error. Either key may be absent. |
| `tasks` | Pending work due within the next 8 days (and anything overdue), sorted by `due_at`. A task is pending until a run completes it. `due_at` may be in the future. |
| `missed` | Work whose window closed without being done, detected in the last 7 days. Each entry is kept for 7 days. Only `capture` and `fpl-deadline` tasks can be missed. |
| `odds_api` | Credit state from the last The Odds API response, or `null` if none has been seen. |

## Worker rules

**Dispatch `tick`** when at least one task has `due_at <= now` **and** either:
- some due task has `due_at` later than the last dispatch time, meaning new work arrived; or
- the last dispatch was 30 or more minutes ago, meaning a retry after a failed or dropped run.

**Dispatch `daily`** from its own cron, unconditionally.

**Report a problem** to healthchecks when any of these is true:
- `status.json` is missing, unparsable or has an unknown `schema`;
- `generated_at` is more than 26 hours old;
- `last_success.daily` is missing or more than 26 hours old;
- a task has `due_at` more than 40 minutes in the past, meaning it is overdue;
- a `missed` entry has `window_closed_at` within the last 24 hours;
- `odds_api.credits_remaining` is below 25;
- a GitHub dispatch call failed (non-2xx).
