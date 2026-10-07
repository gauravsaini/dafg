"""Load config from env-style mapping."""
from __future__ import annotations
from src.v04.mf02.config import from_mapping, Config

def load_from_env(env: dict) -> Config:
    mapping = {}
    if "APP_HOST" in env:
        mapping["host"] = env["APP_HOST"]
    if "APP_PORT" in env:
        mapping["port"] = env["APP_PORT"]
    if "APP_DEBUG" in env:
        mapping["debug"] = env["APP_DEBUG"]
    return from_mapping(mapping)
