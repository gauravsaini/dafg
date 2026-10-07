"""TTL cache with injectable clock."""
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
        if self._clock() > exp:
            del self._data[key]
            raise KeyExpired(key)
        return value
    def keys(self):
        return list(self._data.keys())
    def __len__(self):
        return len(self._data)
