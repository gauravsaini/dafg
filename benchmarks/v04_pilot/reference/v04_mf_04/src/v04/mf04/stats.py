"""Todo statistics."""
from __future__ import annotations

def completion_rate(todos) -> float:
    if not todos:
        return 0.0
    done = sum(1 for t in todos if t.completed)
    return done / len(todos)
