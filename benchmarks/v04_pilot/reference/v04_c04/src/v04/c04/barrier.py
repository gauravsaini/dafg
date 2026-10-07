"""Reusable barrier."""
from __future__ import annotations
import threading

class Barrier:
    def __init__(self, n: int):
        self._n = n
        self._count = 0
        self._cond = threading.Condition()
        self._round = 0
    def wait(self) -> None:
        with self._cond:
            round_ = self._round
            self._count += 1
            if self._count == self._n:
                self._count = 0
                self._round += 1
                self._cond.notify_all()
            else:
                while self._round == round_:
                    self._cond.wait()
