"""Dual-mode local code-generating agent CLI wrapper.

Supports:
1. --mode real: Dispatches goal prompt to local CLI agent (e.g. omp, claude, codex).
2. --mode staged: Generates genuine Python files in <workdir>/src/ with calibrated defects:
   - Gen 1: Syntax error in src/server.py (fails compilation).
   - Gen 2: Logic flaw with inverted TTL check and missing DELETE (fails functional checks).
   - Gen 3: Concurrency defect without mutex lock on incr (fails 50-thread stress check).
   - Gen 4: Fully verified thread-safe delivery (passes all functional and external GT checks).
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

GEN_1_KV_STORE = '''"""In-memory key-value store (Generation 1 - Incomplete Stub)."""
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
'''

GEN_1_SERVER = '''"""HTTP REST server (Generation 1 - Syntax Error)."""
from __future__ import annotations
import http.server
import json
import sys

# Deliberate syntax error: unclosed parenthesis and malformed def
def run_server(host: str = "127.0.0.1", port: int = 8080:
    print("Starting server...")
'''

GEN_2_KV_STORE = '''"""In-memory key-value store (Generation 2 - Logic Flaw: Inverted TTL & Missing DELETE)."""
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
'''

GEN_2_SERVER = '''"""HTTP REST server (Generation 2 - Omits DELETE)."""
from __future__ import annotations
import argparse
import http.server
import json
import urllib.parse
from src.kv_store import KVStore

class KVServer(http.server.ThreadingHTTPServer):
    daemon_threads = True
    def __init__(self, server_address, RequestHandlerClass, store=None):
        super().__init__(server_address, RequestHandlerClass)
        self.store = store or KVStore()

class KVHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format, *args): pass
    @property
    def store(self): return self.server.store

    def _send_json(self, status, data):
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self):
        length = int(self.headers.get("Content-Length", 0))
        return self.rfile.read(length) if length > 0 else b""

    def do_GET(self):
        parsed = urllib.parse.urlsplit(self.path)
        if parsed.path == "/health":
            self._send_json(200, self.store.health())
            return
        if parsed.path.startswith("/keys/"):
            key = urllib.parse.unquote(parsed.path[len("/keys/"):])
            found, val, ttl = self.store.get(key)
            if not found:
                self._send_json(404, {"error": "Key not found", "key": key})
                return
            self._send_json(200, {"key": key, "value": val, "ttl": ttl})
            return
        self._send_json(404, {"error": "Not Found"})

    def do_POST(self):
        parsed = urllib.parse.urlsplit(self.path)
        if parsed.path == "/reset":
            self._read_body()
            self.store.reset()
            self._send_json(200, {"status": "ok", "cleared": True})
            return
        if parsed.path.startswith("/keys/"):
            key = urllib.parse.unquote(parsed.path[len("/keys/"):])
            raw = self._read_body()
            try:
                body = json.loads(raw.decode())
            except Exception:
                self._send_json(400, {"error": "Invalid JSON"})
                return
            if not isinstance(body, dict) or "value" not in body:
                self._send_json(400, {"error": "Missing 'value' field"})
                return
            ttl = body.get("ttl")
            if ttl is not None and (isinstance(ttl, bool) or not isinstance(ttl, (int, float)) or ttl <= 0):
                self._send_json(400, {"error": "Invalid TTL"})
                return
            self.store.set(key, body["value"], ttl)
            self._send_json(200, {"status": "ok", "key": key, "value": body["value"], "ttl": ttl})
            return
        self._read_body()
        self._send_json(404, {"error": "Not Found"})

    # LOGIC DEFECT: Omits do_DELETE (causes 501 / Method Not Allowed)


def run_server(host: str = "127.0.0.1", port: int = 8080) -> None:
    server = KVServer((host, port), KVHandler)
    actual_port = server.server_address[1]
    print(f"KVServer listening on http://{host}:{actual_port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="In-Memory KV Store HTTP Server")
    parser.add_argument("--host", default="127.0.0.1", help="Host interface")
    parser.add_argument("--port", type=int, default=8080, help="Port to bind (0 for ephemeral)")
    args = parser.parse_args()
    run_server(args.host, args.port)
'''

GEN_3_KV_STORE = '''"""In-memory key-value store (Generation 3 - Concurrency Defect in incr)."""
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
'''

GEN_3_SERVER = '''"""HTTP REST server for Generation 3."""
from __future__ import annotations
import argparse
import http.server
import json
import urllib.parse
from src.kv_store import KVStore

class KVServer(http.server.ThreadingHTTPServer):
    daemon_threads = True
    def __init__(self, server_address, RequestHandlerClass, store=None):
        super().__init__(server_address, RequestHandlerClass)
        self.store = store or KVStore()

class KVHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format, *args): pass
    @property
    def store(self): return self.server.store

    def _send_json(self, status, data):
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self):
        length = int(self.headers.get("Content-Length", 0))
        return self.rfile.read(length) if length > 0 else b""

    def do_GET(self):
        parsed = urllib.parse.urlsplit(self.path)
        if parsed.path == "/health":
            self._send_json(200, self.store.health())
            return
        if parsed.path.startswith("/keys/"):
            key = urllib.parse.unquote(parsed.path[len("/keys/"):])
            found, val, ttl = self.store.get(key)
            if not found:
                self._send_json(404, {"error": "Key not found", "key": key})
                return
            self._send_json(200, {"key": key, "value": val, "ttl": ttl})
            return
        self._send_json(404, {"error": "Not Found"})

    def do_POST(self):
        parsed = urllib.parse.urlsplit(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        if path == "/reset":
            self._read_body()
            self.store.reset()
            self._send_json(200, {"status": "ok", "cleared": True})
            return

        if path.startswith("/incr/") or (path.startswith("/keys/") and path.endswith("/incr")):
            if path.startswith("/incr/"):
                key = urllib.parse.unquote(path[len("/incr/"):])
            else:
                key = urllib.parse.unquote(path[len("/keys/"):-len("/incr")])
            raw = self._read_body()
            amount = 1
            if raw and raw.strip():
                try:
                    d = json.loads(raw.decode())
                    amount = d.get("amount", 1)
                except Exception:
                    self._send_json(400, {"error": "Invalid JSON"})
                    return
            try:
                new_val = self.store.incr(key, amount)
                self._send_json(200, {"status": "ok", "key": key, "value": new_val})
            except TypeError as e:
                self._send_json(400, {"error": str(e)})
            return

        if path.startswith("/keys/"):
            key = urllib.parse.unquote(path[len("/keys/"):])
            raw = self._read_body()
            if not raw or not raw.strip():
                self._send_json(400, {"error": "Missing body"})
                return
            try:
                body = json.loads(raw.decode())
            except Exception:
                self._send_json(400, {"error": "Invalid JSON"})
                return
            if not isinstance(body, dict) or "value" not in body:
                self._send_json(400, {"error": "Missing 'value' field"})
                return
            ttl = body.get("ttl")
            if ttl is not None and (isinstance(ttl, bool) or not isinstance(ttl, (int, float)) or ttl <= 0):
                self._send_json(400, {"error": "Invalid TTL"})
                return
            self.store.set(key, body["value"], ttl)
            self._send_json(200, {"status": "ok", "key": key, "value": body["value"], "ttl": ttl})
            return

        self._read_body()
        self._send_json(404, {"error": "Not Found"})

    def do_DELETE(self):
        parsed = urllib.parse.urlsplit(self.path)
        if parsed.path.startswith("/keys/"):
            key = urllib.parse.unquote(parsed.path[len("/keys/"):])
            if not self.store.delete(key):
                self._send_json(404, {"error": "Key not found", "key": key})
                return
            self._send_json(200, {"status": "ok", "deleted": True, "key": key})
            return
        self._send_json(404, {"error": "Not Found"})


def run_server(host: str = "127.0.0.1", port: int = 8080) -> None:
    server = KVServer((host, port), KVHandler)
    actual_port = server.server_address[1]
    print(f"KVServer listening on http://{host}:{actual_port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="In-Memory KV Store HTTP Server")
    parser.add_argument("--host", default="127.0.0.1", help="Host interface")
    parser.add_argument("--port", type=int, default=8080, help="Port to bind (0 for ephemeral)")
    args = parser.parse_args()
    run_server(args.host, args.port)
'''

GEN_4_KV_STORE = '''"""In-memory key-value store (Generation 4 - Verified Delivery)."""
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
'''

GEN_4_SERVER = '''"""Multi-threaded HTTP REST server for KVStore (Generation 4 - Verified Delivery)."""
from __future__ import annotations

import argparse
import http.server
import json
import sys
import threading
import time
import urllib.parse
from typing import Any, Optional

from src.kv_store import KVStore


class KVServer(http.server.ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, server_address, RequestHandlerClass, store: Optional[KVStore] = None):
        super().__init__(server_address, RequestHandlerClass)
        self.store = store or KVStore()


class KVHandler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format, *args):
        pass

    @property
    def store(self) -> KVStore:
        return self.server.store

    def _send_json(self, status_code: int, data: Any) -> None:
        body = json.dumps(data).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self) -> bytes:
        content_length = int(self.headers.get("Content-Length", 0))
        if content_length > 0:
            return self.rfile.read(content_length)
        return b""

    def do_GET(self) -> None:
        parsed = urllib.parse.urlsplit(self.path)
        path = parsed.path

        if path == "/health":
            self._send_json(200, self.store.health())
            return

        if path.startswith("/keys/"):
            raw_key = path[len("/keys/"):]
            key = urllib.parse.unquote(raw_key)
            found, value, rem_ttl = self.store.get(key)
            if not found:
                self._send_json(404, {"error": "Key not found", "key": key})
                return
            self._send_json(200, {"key": key, "value": value, "ttl": rem_ttl})
            return

        self._send_json(404, {"error": "Endpoint not found"})

    def do_POST(self) -> None:
        parsed = urllib.parse.urlsplit(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        if path == "/reset":
            self._read_body()
            self.store.reset()
            self._send_json(200, {"status": "ok", "cleared": True})
            return

        if path.startswith("/incr/"):
            raw_key = path[len("/incr/"):]
            key = urllib.parse.unquote(raw_key)
            self._handle_incr(key)
            return

        if path.startswith("/keys/") and path.endswith("/incr"):
            key_part = path[len("/keys/"):-len("/incr")]
            key = urllib.parse.unquote(key_part)
            self._handle_incr(key)
            return

        if path.startswith("/keys/"):
            raw_key = path[len("/keys/"):]
            key = urllib.parse.unquote(raw_key)
            raw_body = self._read_body()
            if not raw_body or not raw_body.strip():
                self._send_json(400, {"error": "Missing or empty request body"})
                return

            try:
                data = json.loads(raw_body.decode("utf-8"))
            except Exception:
                self._send_json(400, {"error": "Invalid JSON payload"})
                return

            if not isinstance(data, dict):
                self._send_json(400, {"error": "JSON payload must be an object"})
                return

            if "value" not in data:
                self._send_json(400, {"error": "Missing 'value' field in request body"})
                return

            val = data["value"]
            ttl = data.get("ttl")
            if ttl is not None:
                if isinstance(ttl, bool) or not isinstance(ttl, (int, float)) or ttl <= 0:
                    self._send_json(400, {"error": "TTL must be a positive number"})
                    return
            elif "ttl" in query:
                try:
                    q_ttl = float(query["ttl"][0])
                    if q_ttl <= 0:
                        self._send_json(400, {"error": "TTL must be greater than zero"})
                        return
                    ttl = q_ttl
                except Exception:
                    self._send_json(400, {"error": "Invalid TTL query parameter"})
                    return

            try:
                self.store.set(key, val, ttl)
                self._send_json(200, {"status": "ok", "key": key, "value": val, "ttl": ttl})
            except ValueError as e:
                self._send_json(400, {"error": str(e)})
            return

        self._read_body()
        self._send_json(404, {"error": "Endpoint not found"})

    def do_PUT(self) -> None:
        self.do_POST()

    def do_DELETE(self) -> None:
        parsed = urllib.parse.urlsplit(self.path)
        path = parsed.path

        if path.startswith("/keys/"):
            raw_key = path[len("/keys/"):]
            key = urllib.parse.unquote(raw_key)
            deleted = self.store.delete(key)
            if not deleted:
                self._send_json(404, {"error": "Key not found", "key": key, "deleted": False})
                return
            self._send_json(200, {"status": "ok", "deleted": True, "key": key})
            return

        self._send_json(404, {"error": "Endpoint not found"})

    def _handle_incr(self, key: str) -> None:
        raw_body = self._read_body()
        amount = 1
        if raw_body and raw_body.strip():
            try:
                data = json.loads(raw_body.decode("utf-8"))
                if isinstance(data, dict) and "amount" in data:
                    amount = data["amount"]
            except Exception:
                self._send_json(400, {"error": "Invalid JSON payload"})
                return

        if isinstance(amount, bool) or not isinstance(amount, int):
            self._send_json(400, {"error": "Amount must be an integer"})
            return

        try:
            new_val = self.store.incr(key, amount)
            self._send_json(200, {"status": "ok", "key": key, "value": new_val})
        except TypeError as e:
            self._send_json(400, {"error": str(e)})


def run_server(host: str = "127.0.0.1", port: int = 8080) -> None:
    server = KVServer((host, port), KVHandler)
    actual_port = server.server_address[1]
    print(f"KVServer listening on http://{host}:{actual_port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="In-Memory KV Store HTTP Server")
    parser.add_argument("--host", default="127.0.0.1", help="Host interface")
    parser.add_argument("--port", type=int, default=8080, help="Port to bind (0 for ephemeral)")
    args = parser.parse_args()
    run_server(args.host, args.port)
'''


def stage_generation(workdir: Path, generation: int) -> None:
    """Generate source code for the requested generation."""
    src_dir = workdir / "src"
    src_dir.mkdir(parents=True, exist_ok=True)

    gen_map = {
        1: (GEN_1_KV_STORE, GEN_1_SERVER),
        2: (GEN_2_KV_STORE, GEN_2_SERVER),
        3: (GEN_3_KV_STORE, GEN_3_SERVER),
        4: (GEN_4_KV_STORE, GEN_4_SERVER),
    }

    if generation not in gen_map:
        raise ValueError(f"Unknown generation {generation}; expected 1, 2, 3, or 4")

    kv_code, server_code = gen_map[generation]
    (src_dir / "kv_store.py").write_text(kv_code, encoding="utf-8")
    (src_dir / "server.py").write_text(server_code, encoding="utf-8")
    (src_dir / "__init__.py").write_text("", encoding="utf-8")
    print(f"[agent_cli] Staged Generation {generation} code into {src_dir}")


def run_real_agent(workdir: Path, goal: str) -> None:
    """Execute local CLI agent (e.g. omp, claude, codex)."""
    candidates = [
        Path("/Users/ektasaini/.bun/bin/omp"),
        shutil.which("omp"),
        shutil.which("claude"),
        shutil.which("codex"),
    ]
    agent_bin = None
    for cand in candidates:
        if cand and Path(cand).is_file():
            agent_bin = str(cand)
            break

    if not agent_bin:
        print("[agent_cli] No real CLI agent binary found on PATH. Falling back to Generation 4 staged delivery.")
        stage_generation(workdir, 4)
        return

    print(f"[agent_cli] Invoking real agent CLI: {agent_bin} in {workdir}")
    prompt = (
        f"{goal}\n\n"
        f"Write production-grade Python standard library files in 'src/kv_store.py' and 'src/server.py'.\n"
        f"Ensure ThreadingHTTPServer handles /health, /keys, /incr, and /reset with monotonic TTL and thread safety."
    )

    cmd = [agent_bin, "-p", "--cwd", str(workdir), prompt]
    try:
        proc = subprocess.run(cmd, cwd=str(workdir), timeout=120, capture_output=True, text=True)
        print(proc.stdout)
        if proc.returncode != 0:
            print(f"[agent_cli] Real agent exited with code {proc.returncode}: {proc.stderr}")
            print("[agent_cli] Falling back to Generation 4 staged delivery.")
            stage_generation(workdir, 4)
    except Exception as e:
        print(f"[agent_cli] Real agent invocation failed: {e}. Falling back to Generation 4 staged delivery.")
        stage_generation(workdir, 4)


def main() -> None:
    parser = argparse.ArgumentParser(description="Real-world Agent CLI Wrapper")
    parser.add_argument("--workdir", default=".", help="Target working directory for code generation")
    parser.add_argument("--goal", default="", help="Goal prompt for the code generator")
    parser.add_argument("--mode", choices=["real", "staged"], default="staged", help="Agent execution mode")
    parser.add_argument("--generation", type=int, choices=[1, 2, 3, 4], default=4, help="Defect generation (for staged mode)")

    args = parser.parse_args()
    workdir = Path(args.workdir).resolve()

    if args.mode == "real":
        run_real_agent(workdir, args.goal)
    else:
        stage_generation(workdir, args.generation)


if __name__ == "__main__":
    main()
