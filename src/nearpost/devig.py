"""Turn bookmaker decimal odds into probabilities by removing the margin."""

from __future__ import annotations

import math
from collections.abc import Sequence

Probabilities = tuple[float, ...]


def _inverse(odds: Sequence[float]) -> list[float]:
    if not all(math.isfinite(o) and o > 1.0 for o in odds):
        raise ValueError(f"decimal odds must all be finite and > 1.0, got {tuple(odds)}")
    return [1.0 / o for o in odds]


def proportional(odds: Sequence[float]) -> Probabilities:
    """Scale implied probabilities down evenly. Used for two-way markets such as over/under."""
    inverse = _inverse(odds)
    booksum = sum(inverse)
    return tuple(p / booksum for p in inverse)


def shin(odds: Sequence[float], *, tolerance: float = 1e-12, max_iter: int = 1000) -> Probabilities:
    """Shin (1993) de-vig, which corrects the favourite-longshot bias.

    Salvaged from the old project: Jullien & Salanié fixed-point iteration for the
    insider fraction z (as in mberk/shin). Needs three or more outcomes; the
    iteration divides by n - 2.
    """
    n = len(odds)
    if n < 3:
        raise ValueError("shin needs at least three outcomes; use proportional for two-way markets")
    inverse = _inverse(odds)
    booksum = sum(inverse)
    if booksum <= 1.0:
        return tuple(p / booksum for p in inverse)

    z = 0.0
    for _ in range(max_iter):
        previous = z
        z = (sum(math.sqrt(z**2 + 4 * (1 - z) * p**2 / booksum) for p in inverse) - 2) / (n - 2)
        if abs(z - previous) < tolerance:
            break

    probs = [(math.sqrt(z**2 + 4 * (1 - z) * p**2 / booksum) - z) / (2 * (1 - z)) for p in inverse]
    total = sum(probs)
    return tuple(p / total for p in probs)
