"""Simple ledger."""
from __future__ import annotations
from src.v04.mf03.money import Money

class Ledger:
    def __init__(self):
        self._entries = []
    def post(self, account: str, money: Money) -> None:
        self._entries.append((account, money))
    def entries(self):
        return list(self._entries)
    def balance(self, account: str, currency: str) -> Money:
        total = 0
        for acct, m in self._entries:
            if acct == account and m.currency == currency:
                total += m.cents
        return Money(total, currency)
