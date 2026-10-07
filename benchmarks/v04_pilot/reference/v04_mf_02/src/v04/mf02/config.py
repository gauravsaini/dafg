"""Config value object with coercion."""
from __future__ import annotations
from dataclasses import dataclass

TRUE_STRINGS = {"true", "1", "yes", "on"}

@dataclass
class Config:
    host: str = "localhost"
    port: int = 8080
    debug: bool = False

def _to_bool(v) -> bool:
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() in TRUE_STRINGS

def from_mapping(m: dict) -> Config:
    return Config(
        host=m.get("host", "localhost"),
        port=int(m.get("port", 8080)),
        debug=_to_bool(m.get("debug", False)),
    )
