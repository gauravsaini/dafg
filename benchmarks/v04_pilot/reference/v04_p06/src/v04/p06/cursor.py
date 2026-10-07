"""Opaque pagination cursors."""
from __future__ import annotations
import base64

class BadCursor(Exception):
    pass

def encode(offset: int) -> str:
    return base64.urlsafe_b64encode(str(offset).encode()).decode()

def decode(s: str) -> int:
    try:
        return int(base64.urlsafe_b64decode(s.encode()).decode())
    except Exception:
        raise BadCursor(f"bad cursor: {s!r}")
