"""In-memory key-value store (Generation 4 - Verified Delivery)."""
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
                remaining = expiry - time.monotonic()
                if remaining <= 0:
                    del self._data[key]
                    return False, None, None
                return True, entry["value"], remaining
            return True, entry["value"], None

    def delete(self, key: str) -> bool:
        with self._lock:
            if key not in self._data:
                return False
            entry = self._data[key]
            expiry = entry["expiry"]
            if expiry is not None and time.monotonic() >= expiry:
                del self._data[key]
                return False
            del self._data[key]
            return True

    def incr(self, key: str, amount: int = 1) -> int:
        if isinstance(amount, bool) or not isinstance(amount, int):
            raise TypeError("Amount must be an integer")

        with self._lock:
            entry = self._data.get(key)
            if entry is not None:
                expiry = entry["expiry"]
                if expiry is not None and time.monotonic() >= expiry:
                    del self._data[key]
                    entry = None

            if entry is None:
                new_val = amount
                self._data[key] = {"value": new_val, "expiry": None}
                return new_val

            current_val = entry["value"]
            if isinstance(current_val, bool) or not isinstance(current_val, int):
                raise TypeError("Value is not an integer")

            new_val = current_val + amount
            entry["value"] = new_val
            return new_val

    def reset(self) -> None:
        with self._lock:
            self._data.clear()

    def health(self) -> Dict[str, Any]:
        with self._lock:
            now = time.monotonic()
            expired = [k for k, v in self._data.items() if v["expiry"] is not None and now >= v["expiry"]]
            for k in expired:
                del self._data[k]
            return {
                "status": "healthy",
                "keys_count": len(self._data),
                "uptime_seconds": round(now - self._start_time, 2),
            }
