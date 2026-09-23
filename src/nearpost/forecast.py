from __future__ import annotations

from dataclasses import dataclass

Probs3 = tuple[float, float, float]  # home / draw / away


@dataclass(frozen=True)
class Forecast:
    probs: Probs3
    over_2_5: float | None = None
    btts: float | None = None
    n_books: int | None = None  # market forecasts only: how many books were averaged
