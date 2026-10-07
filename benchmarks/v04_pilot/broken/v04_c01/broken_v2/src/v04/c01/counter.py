"""Counter -- BROKEN: incr adds n+1."""
from __future__ import annotations
import threading

class AtomicCounter:
    def __init__(self):
        self._lock = threading.Lock()
        self._value = 0
    def incr(self, n: int = 1) -> None:
        with self._lock:
            self._value += n + 1
    @property
    def value(self) -> int:
        with self._lock:
            return self._value
