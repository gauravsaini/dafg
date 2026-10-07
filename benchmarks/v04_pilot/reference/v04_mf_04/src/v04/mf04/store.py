"""Todo store."""
from __future__ import annotations
from dataclasses import dataclass

@dataclass
class Todo:
    id: int
    title: str
    due_ts: float
    completed: bool = False

class TodoStore:
    def __init__(self):
        self._todos = {}
        self._next = 1
    def add(self, title: str, due_ts: float) -> int:
        tid = self._next
        self._todos[tid] = Todo(id=tid, title=title, due_ts=due_ts)
        self._next += 1
        return tid
    def complete(self, tid: int) -> None:
        self._todos[tid].completed = True
    def list_open(self):
        return [t for t in self._todos.values() if not t.completed]
    def all(self):
        return list(self._todos.values())
