"""TTL cache -- BROKEN: get ignores TTL."""
from __future__ import annotations
import time

class KeyExpired(Exception):
    pass

class TTLCache:
    def __init__(self, clock=None):
        self._clock = clock or time.monotonic
        self._data = {}
    def set(self, key, value, ttl_s: float) -> None:
        self._data[key] = (value, self._clock() + ttl_s)
    def get(self, key):
        if key not in self._data:
            raise KeyError(key)
        value, exp = self._data[key]
        return value
    def keys(self):
        return list(self._data.keys())
    def __len__(self):
        return len(self._data)
