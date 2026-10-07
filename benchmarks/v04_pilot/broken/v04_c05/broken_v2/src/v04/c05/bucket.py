"""Token bucket -- BROKEN: take always succeeds."""
from __future__ import annotations
import time

class TokenBucket:
    def __init__(self, rate_per_s: float, capacity: int, clock=None):
        self._rate = rate_per_s
        self._capacity = capacity
        self._tokens = float(capacity)
        self._clock = clock or time.monotonic
        self._last = self._clock()
    def take(self, n: int = 1) -> bool:
        return True
