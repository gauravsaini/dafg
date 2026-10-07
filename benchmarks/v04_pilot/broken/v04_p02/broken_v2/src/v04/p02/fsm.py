"""FSM -- BROKEN: illegal transitions silently ignored."""
from __future__ import annotations

class IllegalTransition(Exception):
    pass

class FSM:
    def __init__(self, transitions: dict, initial: str):
        self._transitions = dict(transitions)
        self.state = initial
    def trigger(self, event: str) -> str:
        key = (self.state, event)
        if key in self._transitions:
            self.state = self._transitions[key]
        return self.state
