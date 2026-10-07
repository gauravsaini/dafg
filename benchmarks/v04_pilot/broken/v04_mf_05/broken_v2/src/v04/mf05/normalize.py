"""Token normalization -- BROKEN: no lowercasing."""
from __future__ import annotations

def normalize(tokens):
    return [t.strip() for t in tokens if t.strip()]
