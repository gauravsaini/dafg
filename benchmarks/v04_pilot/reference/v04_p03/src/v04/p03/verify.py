"""Audit log verification."""
from __future__ import annotations

def check_monotonic(entries) -> bool:
    return [e["seq"] for e in entries] == list(range(1, len(entries) + 1))
