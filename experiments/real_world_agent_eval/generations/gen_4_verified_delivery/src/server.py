"""Multi-threaded HTTP REST server for KVStore (Generation 4 - Verified Delivery)."""
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
    request_queue_size = 128

    def __init__(self, server_address, RequestHandlerClass, store: Optional[KVStore] = None):
        super().__init__(server_address, RequestHandlerClass)
        self.store = store or KVStore()


class KVHandler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

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
        try:
            self.wfile.flush()
        except Exception:
            pass

    def _read_body(self) -> bytes:
        try:
            content_length = int(self.headers.get("Content-Length", 0))
        except (ValueError, TypeError):
            content_length = 0
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
