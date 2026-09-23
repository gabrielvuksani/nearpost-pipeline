"""Boundary validation for bookmaker prices from any source."""

from __future__ import annotations

import math
from typing import Any


def decimal_price(value: Any) -> float | None:
    """A usable decimal price, or None. A price must be finite and above 1.0 (1.0 means a
    certain outcome and would break de-vigging); anything else is treated as not offered."""
    try:
        price = float(value)
    except (TypeError, ValueError):
        return None
    return price if math.isfinite(price) and price > 1.0 else None
