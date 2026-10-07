"""Todo filters (explicit now -- no wall clock)."""
from __future__ import annotations

def overdue(todos, now_ts: float):
    return [t for t in todos if not t.completed and t.due_ts < now_ts]
