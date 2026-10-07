"""Backoff -- BROKEN: constant delay."""
from __future__ import annotations

def backoff_delay(attempt: int, base: float = 1.0, cap: float = 30.0) -> float:
    return base
