"""Shared store guarded by RWLock."""
from __future__ import annotations
from src.v04.c06.rwlock import RWLock

class SharedStore:
    def __init__(self):
        self._rw = RWLock()
        self._data = {}
    def read(self, key):
        with self._rw.read():
            return self._data.get(key)
    def write(self, key, value):
        with self._rw.write():
            self._data[key] = value
