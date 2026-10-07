"""User service layer."""
from __future__ import annotations
from src.v04.mf01.models import User, validate_username

class UserService:
    def __init__(self) -> None:
        self._users = {}
        self._next_id = 1
    def create(self, username: str) -> User:
        validate_username(username)
        user = User(id=self._next_id, username=username)
        self._users[user.id] = user
        self._next_id += 1
        return user
    def get(self, uid: int) -> User:
        return self._users[uid]
    def deactivate(self, uid: int) -> None:
        self._users[uid].active = False
