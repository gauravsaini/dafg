"""Money value object -- BROKEN: __add__ ignores currency."""
from __future__ import annotations
from dataclasses import dataclass

class CurrencyMismatch(Exception):
    pass

@dataclass(frozen=True)
class Money:
    cents: int
    currency: str
    def _check(self, other):
        if self.currency != other.currency:
            raise CurrencyMismatch(f"{self.currency} != {other.currency}")
    def __add__(self, other):
        return Money(self.cents + other.cents, self.currency)
    def __sub__(self, other):
        self._check(other)
        return Money(self.cents - other.cents, self.currency)
