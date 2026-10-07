"""Pricing math."""
from __future__ import annotations

def discounted(price_cents: int, pct: float) -> int:
    if not (0 <= pct <= 100):
        raise ValueError("pct must be in [0, 100]")
    return int(price_cents * (100 - pct) / 100)
