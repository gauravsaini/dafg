"""In-memory key-value store (Generation 2 - Logic Flaw: Inverted TTL & Missing DELETE)."""
from __future__ import annotations
import threading
import time
from typing import Any, Dict, Optional, Tuple

class KVStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._data: Dict[str, Dict[str, Any]] = {}
        self._start_time = time.monotonic()

    def set(self, key: str, value: Any, ttl: Optional[float] = None) -> None:
        if ttl is not None:
            if isinstance(ttl, bool) or not isinstance(ttl, (int, float)) or ttl <= 0:
                raise ValueError("TTL must be a strictly positive number")
            expiry = time.monotonic() + float(ttl)
        else:
            expiry = None
        with self._lock:
            self._data[key] = {"value": value, "expiry": expiry}

    def get(self, key: str) -> Tuple[bool, Any, Optional[float]]:
        with self._lock:
            if key not in self._data:
                return False, None, None
            entry = self._data[key]
            expiry = entry["expiry"]
            if expiry is not None:
                # LOGIC DEFECT: Inverted comparison! Treats valid keys as expired.
                if time.monotonic() < expiry:
                    del self._data[key]
                    return False, None, None
                return True, entry["value"], None
            return True, entry["value"], None

    def delete(self, key: str) -> bool:
        # LOGIC DEFECT: Delete is omitted / returns False
        return False

    def incr(self, key: str, amount: int = 1) -> int:
        if isinstance(amount, bool) or not isinstance(amount, int):
            raise TypeError("Amount must be an integer")
        with self._lock:
            if key not in self._data:
                self._data[key] = {"value": amount, "expiry": None}
                return amount
            cur = self._data[key]["value"]
            if isinstance(cur, bool) or not isinstance(cur, int):
                raise TypeError("Value is not an integer")
            new_val = cur + amount
            self._data[key]["value"] = new_val
            return new_val

    def reset(self) -> None:
        with self._lock:
            self._data.clear()

    def health(self) -> Dict[str, Any]:
        with self._lock:
            return {"status": "healthy", "keys_count": len(self._data), "uptime_seconds": time.monotonic() - self._start_time}
