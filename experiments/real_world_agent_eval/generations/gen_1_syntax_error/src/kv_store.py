"""In-memory key-value store (Generation 1 - Incomplete Stub)."""
from __future__ import annotations
import time
from typing import Any, Dict, Optional, Tuple

class KVStore:
    def __init__(self) -> None:
        self._data: Dict[str, Any] = {}

    def set(self, key: str, value: Any, ttl: Optional[float] = None) -> None:
        self._data[key] = value

    def get(self, key: str) -> Tuple[bool, Any, Optional[float]]:
        if key in self._data:
            return True, self._data[key], None
        return False, None, None
