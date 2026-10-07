"""User domain model."""
from __future__ import annotations
from dataclasses import dataclass

@dataclass
class User:
    id: int
    username: str
    active: bool = True

def validate_username(name: str) -> str:
    if not name or len(name) > 32 or not all(c.isalnum() or c == "_" for c in name):
        raise ValueError(f"invalid username: {name!r}")
    return name
