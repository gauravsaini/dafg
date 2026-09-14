"""In-memory key-value store (Generation 3 - Concurrency Defect in incr)."""
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
                rem = expiry - time.monotonic()
                if rem <= 0:
                    del self._data[key]
                    return False, None, None
                return True, entry["value"], rem
            return True, entry["value"], None

    def delete(self, key: str) -> bool:
        with self._lock:
            if key not in self._data:
                return False
            entry = self._data[key]
            if entry["expiry"] is not None and time.monotonic() >= entry["expiry"]:
                del self._data[key]
                return False
            del self._data[key]
            return True

    def incr(self, key: str, amount: int = 1) -> int:
        if isinstance(amount, bool) or not isinstance(amount, int):
            raise TypeError("Amount must be an integer")
        # CONCURRENCY DEFECT: Unsynchronized read-modify-write without self._lock
        entry = self._data.get(key)
        cur = entry["value"] if entry and not isinstance(entry["value"], bool) and isinstance(entry["value"], int) else 0
        time.sleep(0.0001)  # Micro-yield ensures context switch and lost updates under 50 threads
        new_val = cur + amount
        self._data[key] = {"value": new_val, "expiry": None}
        return new_val

    def reset(self) -> None:
        with self._lock:
            self._data.clear()

    def health(self) -> Dict[str, Any]:
        with self._lock:
            return {"status": "healthy", "keys_count": len(self._data), "uptime_seconds": round(time.monotonic() - self._start_time, 2)}
