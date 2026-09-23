"""Aggregate scores from the ledger: each model and horizon, paired against closing lines.

Derived and recomputable at any time from the ledger alone. The headline number is the
paired difference (model minus close, match by match): lower than zero means we beat it.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from statistics import fmean
from typing import Any

from nearpost.ledger.chain import Entry
from nearpost.market import ODDS_API_MODEL_ID

METRICS = ("rps", "log_loss", "brier")
OUR_CLOSE = (ODDS_API_MODEL_ID, "T-15m")
FOOTBALL_DATA_CLOSE = "football-data-avg"


def _summary(rows: list[dict[str, float]]) -> dict[str, Any]:
    return {"n": len(rows), **{m: (round(fmean(r[m] for r in rows), 6) if rows else None) for m in METRICS}}


def _paired(model_rows: dict[str, dict[str, float]], close_rows: dict[str, dict[str, float]]) -> dict[str, Any]:
    shared = sorted(set(model_rows) & set(close_rows))
    return _summary([{m: model_rows[k][m] - close_rows[k][m] for m in METRICS} for k in shared])


def build_scoreboard(entries: Iterable[Entry], *, generated_at: str) -> dict[str, Any]:
    by_track: dict[tuple[str, str], dict[str, dict[str, float]]] = defaultdict(dict)
    closes: dict[str, dict[str, dict[str, float]]] = defaultdict(dict)
    settled = 0
    for entry in entries:
        body = entry.body
        if entry.kind == "settlement":
            settled += 1
            for score in body["scores"]:
                by_track[(score["model"], score["horizon"])][body["match_id"]] = score
        elif entry.kind == "benchmark":
            for name, close in body["closes"].items():
                closes[name][body["match_id"]] = close["scores"]

    our_close = by_track.get(OUR_CLOSE, {})
    tracks: dict[str, dict[str, Any]] = defaultdict(dict)
    for (model, horizon), rows in sorted(by_track.items()):
        row = _summary(list(rows.values()))
        if (model, horizon) != OUR_CLOSE:
            row["vs_our_close"] = _paired(rows, our_close)
        row["vs_football_data_close"] = _paired(rows, closes.get(FOOTBALL_DATA_CLOSE, {}))
        tracks[model][horizon] = row

    return {
        "generated_at": generated_at,
        "matches_settled": settled,
        "tracks": dict(tracks),
        "closes": {name: _summary(list(rows.values())) for name, rows in sorted(closes.items())},
    }
