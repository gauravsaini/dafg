"""Word counting."""
from __future__ import annotations

def word_counts(tokens):
    d = {}
    for t in tokens:
        d[t] = d.get(t, 0) + 1
    return d
