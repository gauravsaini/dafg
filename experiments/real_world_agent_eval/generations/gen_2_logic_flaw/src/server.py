"""HTTP REST server (Generation 2 - Omits DELETE)."""
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
