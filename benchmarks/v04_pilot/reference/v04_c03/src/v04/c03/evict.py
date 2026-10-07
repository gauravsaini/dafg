"""Expiry eviction."""
from __future__ import annotations
from src.v04.c03.cache import KeyExpired

def evict_expired(cache) -> int:
    removed = 0
    for k in cache.keys():
        try:
            cache.get(k)
        except KeyExpired:
            removed += 1
        except KeyError:
            pass
    return removed
