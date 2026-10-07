"""Config validation."""
from __future__ import annotations
from src.v04.mf02.config import Config

def validate(cfg: Config):
    errors = []
    if not cfg.host:
        errors.append("host required")
    if not (1 <= cfg.port <= 65535):
        errors.append("port out of range")
    return errors
