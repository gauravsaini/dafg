"""Read-write lock."""
from __future__ import annotations
import threading
from contextlib import contextmanager

class RWLock:
    def __init__(self):
        self._lock = threading.Lock()
        self._readers = 0
        self._read_ok = threading.Condition(self._lock)
        self._writer = False
    @contextmanager
    def read(self):
        with self._lock:
            while self._writer:
                self._read_ok.wait()
            self._readers += 1
        try:
            yield
        finally:
            with self._lock:
                self._readers -= 1
                if self._readers == 0:
                    self._read_ok.notify_all()
    @contextmanager
    def write(self):
        with self._lock:
            while self._writer or self._readers > 0:
                self._read_ok.wait()
            self._writer = True
        try:
            yield
        finally:
            with self._lock:
                self._writer = False
                self._read_ok.notify_all()
