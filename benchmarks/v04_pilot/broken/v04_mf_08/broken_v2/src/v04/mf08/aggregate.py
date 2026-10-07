"""Aggregation -- BROKEN: no int conversion (TypeError on str)."""
from __future__ import annotations

def sum_by_key(rows, group_key: str, sum_key: str):
    totals = {}
    for r in rows:
        totals[r[group_key]] = totals.get(r[group_key], 0) + r[sum_key]
    return totals
