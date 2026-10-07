"""Append-only audit log with monotonic sequence numbers."""
from __future__ import annotations

class AuditLog:
    def __init__(self):
        self._entries = []
    def append(self, action: str) -> dict:
        entry = {"seq": len(self._entries) + 1, "action": action}
        self._entries.append(entry)
        return entry
    def entries(self):
        return list(self._entries)
