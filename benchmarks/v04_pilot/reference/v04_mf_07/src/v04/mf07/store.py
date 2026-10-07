"""Revocation list."""
from __future__ import annotations

class RevocationList:
    def __init__(self):
        self._revoked = set()
    def revoke(self, sig: str) -> None:
        self._revoked.add(sig)
    def is_revoked(self, sig: str) -> bool:
        return sig in self._revoked
