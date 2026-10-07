"""Trial balance report."""
from __future__ import annotations

def trial_balance(ledger, currency: str):
    totals = {}
    for acct, m in ledger.entries():
        if m.currency == currency:
            totals[acct] = totals.get(acct, 0) + m.cents
    return totals
