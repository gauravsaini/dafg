"""HTTP-ish controller (no framework)."""
from __future__ import annotations
from src.v04.mf01.services import UserService

def handle_create(service: UserService, payload: dict):
    if "username" not in payload:
        return 422, {"error": "username required"}
    try:
        user = service.create(payload["username"])
    except ValueError as exc:
        return 400, {"error": str(exc)}
    return 201, {"id": user.id, "username": user.username}
