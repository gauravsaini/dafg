"""Token bucket with injectable clock."""
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
        now = self._clock()
        self._tokens = min(self._capacity, self._tokens + (now - self._last) * self._rate)
        self._last = now
        if self._tokens >= n:
            self._tokens -= n
            return True
        return False
