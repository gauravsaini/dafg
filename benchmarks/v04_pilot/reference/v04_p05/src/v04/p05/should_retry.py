"""Retry decisions."""
from __future__ import annotations

def should_retry(status: int, attempt: int, max_attempts: int) -> bool:
    if attempt >= max_attempts:
        return False
    if status == 429 or 500 <= status <= 599:
        return True
    return False
