"""Token normalization."""
from __future__ import annotations

def normalize(tokens):
    return [t.strip().lower() for t in tokens if t.strip()]
