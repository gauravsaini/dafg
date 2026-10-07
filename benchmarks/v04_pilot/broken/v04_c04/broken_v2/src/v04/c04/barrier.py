"""Barrier -- BROKEN: single-use only, raises on reuse."""
from __future__ import annotations
import threading

class Barrier:
    def __init__(self, n: int):
        self._n = n
        self._count = 0
        self._uses = 0
        self._cond = threading.Condition()
        self._round = 0
    def wait(self) -> None:
        with self._cond:
            self._uses += 1
            if self._uses > self._n:
                raise RuntimeError("barrier single-use only")
            round_ = self._round
            self._count += 1
            if self._count == self._n:
                self._count = 0
                self._round += 1
                self._cond.notify_all()
            else:
                while self._round == round_:
                    self._cond.wait()
