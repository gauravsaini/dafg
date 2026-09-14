"""Objective functional gate test harness for Real-World Agent Evaluation.

Executed by GATES.md via:
    uv run python test_service.py <TEST>
Supported suites:
    CORE        - Direct verification of KVStore class (set, get, delete, monotonic TTL)
    STORAGE     - Data persistence, type preservation, null distinction, reset
    PROTOCOL    - HTTP REST server endpoints over loopback TCP (health, keys, incr, delete, error codes)
    CONCURRENCY - Atomic increment under 50 concurrent worker threads
    E2E         - Full end-to-end integration test against running server

Standard library only. NO self-referential pass-through or fake stubs.
"""
from __future__ import annotations

import http.client
import json
import os
import socket
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Module Discovery & Resolution
# ---------------------------------------------------------------------------

def _resolve_workdir() -> Path:
    candidates = [
        os.environ.get("KV_SERVER_WORKDIR"),
        Path.cwd(),
        Path(__file__).resolve().parent.parent,
        Path(__file__).resolve().parent,
    ]
    for cand in candidates:
        if cand:
            p = Path(cand).resolve()
            if (p / "src" / "kv_store.py").is_file():
                return p
    return Path.cwd().resolve()


WORKDIR = _resolve_workdir()
if str(WORKDIR) not in sys.path:
    sys.path.insert(0, str(WORKDIR))


# ---------------------------------------------------------------------------
# HTTP Client Helper
# ---------------------------------------------------------------------------

def http_req(
    url: str,
    method: str = "GET",
    data: Optional[Any] = None,
    raw_body: Optional[bytes] = None,
    headers: Optional[Dict[str, str]] = None,
    timeout: float = 5.0,
) -> Tuple[int, Any, Dict[str, str]]:
    """Execute HTTP request using stdlib urllib.request."""
    hdrs: Dict[str, str] = {
        "Accept": "application/json",
        "Connection": "close",
    }
    if headers:
        hdrs.update(headers)

    body_bytes: Optional[bytes] = None
    if raw_body is not None:
        body_bytes = raw_body
        hdrs.setdefault("Content-Type", "application/json")
        hdrs["Content-Length"] = str(len(body_bytes))
    elif data is not None:
        body_bytes = json.dumps(data).encode("utf-8")
        hdrs.setdefault("Content-Type", "application/json")
        hdrs["Content-Length"] = str(len(body_bytes))
    elif method.upper() in ("POST", "PUT"):
        hdrs.setdefault("Content-Length", "0")

    req = urllib.request.Request(url, data=body_bytes, method=method.upper(), headers=hdrs)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            content = resp.read()
            try:
                payload = json.loads(content.decode("utf-8"))
            except Exception:
                payload = content.decode("utf-8", errors="replace")
            return resp.status, payload, dict(resp.headers)
    except urllib.error.HTTPError as e:
        content = e.read()
        try:
            payload = json.loads(content.decode("utf-8"))
        except Exception:
            payload = content.decode("utf-8", errors="replace")
        return e.code, payload, dict(e.headers)


def wait_until_healthy(base_url: str, timeout: float = 5.0) -> None:
    start = time.monotonic()
    last_err = None
    while (time.monotonic() - start) < timeout:
        try:
            status, data, _ = http_req(f"{base_url}/health", method="GET", timeout=1.0)
            if status == 200 and isinstance(data, dict) and data.get("status") in ("ok", "healthy"):
                return
        except Exception as e:
            last_err = e
        time.sleep(0.05)
    raise TimeoutError(f"Server at {base_url} failed to become healthy within {timeout}s: {last_err}")


def spawn_test_server() -> Tuple[Any, str]:
    """Start KVServer in a background daemon thread on an ephemeral port."""
    from src.server import KVServer, KVHandler
    from src.kv_store import KVStore

    store = KVStore()
    server = KVServer(("127.0.0.1", 0), KVHandler, store=store)
    port = server.server_address[1]
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    base_url = f"http://127.0.0.1:{port}"
    wait_until_healthy(base_url)
    return server, base_url


# ---------------------------------------------------------------------------
# Test Suites
# ---------------------------------------------------------------------------

def run_core_suite() -> None:
    """Test G1: KVStore Core Engine & Monotonic TTL."""
    try:
        from src.kv_store import KVStore
    except Exception as e:
        sys.stderr.write(f"CORE FAIL: Cannot import KVStore from src.kv_store: {e}\n")
        sys.exit(1)

    store = KVStore()

    # 1. Basic Set and Get
    store.set("test_k1", "val1")
    found, val, ttl = store.get("test_k1")
    if not found or val != "val1" or ttl is not None:
        sys.stderr.write(f"CORE FAIL: Basic set/get failed: found={found}, val={val}, ttl={ttl}\n")
        sys.exit(1)

    # 2. Delete
    deleted = store.delete("test_k1")
    if not deleted:
        sys.stderr.write("CORE FAIL: Delete existing key returned False\n")
        sys.exit(1)
    found_after, _, _ = store.get("test_k1")
    if found_after:
        sys.stderr.write("CORE FAIL: Deleted key still returned found=True\n")
        sys.exit(1)
    if store.delete("test_k1"):
        sys.stderr.write("CORE FAIL: Delete missing key returned True\n")
        sys.exit(1)

    # 3. Monotonic TTL Expiration
    store.set("ephemeral", "short_lived", ttl=0.15)
    found, val, rem_ttl = store.get("ephemeral")
    if not found:
        sys.stderr.write("CORE FAIL: Ephemeral key was not found immediately after set (TTL inverted?)\n")
        sys.exit(1)
    if val != "short_lived" or rem_ttl is None or not (0.0 < rem_ttl <= 0.2):
        sys.stderr.write(f"CORE FAIL: Unexpected TTL on immediate read: rem_ttl={rem_ttl}\n")
        sys.exit(1)

    time.sleep(0.20)
    found_expired, _, _ = store.get("ephemeral")
    if found_expired:
        sys.stderr.write("CORE FAIL: Ephemeral key did not expire after TTL passed\n")
        sys.exit(1)

    # 4. Overwrite clears TTL
    store.set("cleared_ttl", "initial", ttl=0.15)
    store.set("cleared_ttl", "persistent")
    time.sleep(0.20)
    found_persisted, val_p, ttl_p = store.get("cleared_ttl")
    if not found_persisted or val_p != "persistent" or ttl_p is not None:
        sys.stderr.write("CORE FAIL: Overwriting key without TTL did not clear TTL\n")
        sys.exit(1)

    # 5. Invalid TTL validation
    try:
        store.set("bad_ttl", "val", ttl=-5)
        sys.stderr.write("CORE FAIL: set() accepted negative TTL without raising ValueError\n")
        sys.exit(1)
    except ValueError:
        pass

    print("CORE_PASS")


def run_storage_suite() -> None:
    """Test G2: Storage Engine & JSON Type Preservation."""
    try:
        from src.kv_store import KVStore
    except Exception as e:
        sys.stderr.write(f"STORAGE FAIL: Cannot import KVStore: {e}\n")
        sys.exit(1)

    store = KVStore()

    # 1. Type preservation
    cases: Dict[str, Any] = {
        "k_int": 999999,
        "k_float": 12.3456,
        "k_bool_t": True,
        "k_bool_f": False,
        "k_list": [1, "two", 3.0, None],
        "k_dict": {"alpha": 1, "beta": [True, False], "gamma": {"nested": "value"}},
    }
    for k, expected_v in cases.items():
        store.set(k, expected_v)
        found, actual_v, _ = store.get(k)
        if not found or actual_v != expected_v or type(actual_v) is not type(expected_v):
            sys.stderr.write(f"STORAGE FAIL: Type mismatch for {k}: expected {expected_v}, got {actual_v}\n")
            sys.exit(1)

    # 2. Explicit null distinction
    store.set("null_key", None)
    found_null, val_null, _ = store.get("null_key")
    if not found_null or val_null is not None:
        sys.stderr.write(f"STORAGE FAIL: Explicit null key returned found={found_null}, val={val_null}\n")
        sys.exit(1)

    found_missing, val_missing, _ = store.get("nonexistent_key_999")
    if found_missing:
        sys.stderr.write("STORAGE FAIL: Missing key returned found=True\n")
        sys.exit(1)

    # 3. Reset
    store.reset()
    for k in cases:
        f, _, _ = store.get(k)
        if f:
            sys.stderr.write(f"STORAGE FAIL: Key {k} still present after reset\n")
            sys.exit(1)

    print("STORAGE_PASS")


def run_protocol_suite() -> None:
    """Test G3: HTTP REST API Protocol & Error Handling."""
    try:
        from src.server import KVServer, KVHandler
    except Exception as e:
        sys.stderr.write(f"PROTOCOL FAIL: Cannot import server: {e}\n")
        sys.exit(1)

    server, base_url = spawn_test_server()
    try:
        # 1. Health
        st, body, hdrs = http_req(f"{base_url}/health")
        if st != 200 or not isinstance(body, dict) or body.get("status") not in ("ok", "healthy"):
            sys.stderr.write(f"PROTOCOL FAIL: /health returned {st}: {body}\n")
            sys.exit(1)
        if "application/json" not in hdrs.get("Content-Type", ""):
            sys.stderr.write(f"PROTOCOL FAIL: Missing Content-Type application/json header\n")
            sys.exit(1)

        # 2. POST /keys/<key> and GET
        st, body, _ = http_req(f"{base_url}/keys/proto_k", method="POST", data={"value": "proto_v"})
        if st not in (200, 201):
            sys.stderr.write(f"PROTOCOL FAIL: POST /keys/proto_k returned {st}: {body}\n")
            sys.exit(1)

        st, body, _ = http_req(f"{base_url}/keys/proto_k", method="GET")
        if st != 200 or body.get("value") != "proto_v":
            sys.stderr.write(f"PROTOCOL FAIL: GET /keys/proto_k returned {st}: {body}\n")
            sys.exit(1)

        # 3. DELETE /keys/<key>
        st, body, _ = http_req(f"{base_url}/keys/proto_k", method="DELETE")
        if st != 200 or not body.get("deleted"):
            sys.stderr.write(f"PROTOCOL FAIL: DELETE /keys/proto_k returned {st}: {body}\n")
            sys.exit(1)

        st, body, _ = http_req(f"{base_url}/keys/proto_k", method="GET")
        if st != 404:
            sys.stderr.write(f"PROTOCOL FAIL: Deleted key returned {st} instead of 404\n")
            sys.exit(1)

        # 4. Increments: both /incr/<key> and /keys/<key>/incr
        st1, b1, _ = http_req(f"{base_url}/incr/c1", method="POST", data={"amount": 5})
        if st1 != 200 or b1.get("value") != 5:
            sys.stderr.write(f"PROTOCOL FAIL: POST /incr/c1 returned {st1}: {b1}\n")
            sys.exit(1)

        st2, b2, _ = http_req(f"{base_url}/keys/c2/incr", method="POST", data={"amount": 10})
        if st2 != 200 or b2.get("value") != 10:
            sys.stderr.write(f"PROTOCOL FAIL: POST /keys/c2/incr returned {st2}: {b2}\n")
            sys.exit(1)

        # 5. Error codes (400 Bad Request)
        # Malformed JSON
        st, _, _ = http_req(f"{base_url}/keys/bad_json", method="POST", raw_body=b"{malformed_json")
        if st != 400:
            sys.stderr.write(f"PROTOCOL FAIL: Malformed JSON returned {st} instead of 400\n")
            sys.exit(1)

        # Missing value
        st, _, _ = http_req(f"{base_url}/keys/no_val", method="POST", data={"ttl": 10})
        if st != 400:
            sys.stderr.write(f"PROTOCOL FAIL: Missing value returned {st} instead of 400\n")
            sys.exit(1)

        # Invalid TTL
        st, _, _ = http_req(f"{base_url}/keys/bad_ttl", method="POST", data={"value": 1, "ttl": -5})
        if st != 400:
            sys.stderr.write(f"PROTOCOL FAIL: Negative TTL returned {st} instead of 400\n")
            sys.exit(1)

        # Non-integer incr
        http_req(f"{base_url}/keys/str_key", method="POST", data={"value": "text"})
        st, _, _ = http_req(f"{base_url}/incr/str_key", method="POST")
        if st != 400:
            sys.stderr.write(f"PROTOCOL FAIL: Incr on string returned {st} instead of 400\n")
            sys.exit(1)

        # 6. URL Percent Encoding
        st, _, _ = http_req(f"{base_url}/keys/user%3A101%2Ftest", method="POST", data={"value": 77})
        if st not in (200, 201):
            sys.stderr.write(f"PROTOCOL FAIL: Percent-encoded key POST returned {st}\n")
            sys.exit(1)

        st, b_enc, _ = http_req(f"{base_url}/keys/user%3A101%2Ftest", method="GET")
        if st != 200 or b_enc.get("key") != "user:101/test" or b_enc.get("value") != 77:
            sys.stderr.write(f"PROTOCOL FAIL: Percent-encoded key GET mismatch: {b_enc}\n")
            sys.exit(1)

    finally:
        server.shutdown()
        server.server_close()

    print("PROTOCOL_PASS")


def run_concurrency_suite() -> None:
    """Test G4: Atomic Concurrency & Mutex Linearizability."""
    try:
        from src.server import KVServer, KVHandler
    except Exception as e:
        sys.stderr.write(f"CONCURRENCY FAIL: Cannot import server: {e}\n")
        sys.exit(1)

    server, base_url = spawn_test_server()
    num_threads = 50
    ops_per_thread = 10
    total_expected = num_threads * ops_per_thread
    key = "concurrent_counter"

    barrier = threading.Barrier(num_threads)
    returned_values: List[int] = []
    errors: List[Exception] = []
    val_lock = threading.Lock()

    def worker(wid: int) -> None:
        barrier.wait()
        for _ in range(ops_per_thread):
            try:
                st, body, _ = http_req(f"{base_url}/incr/{key}", method="POST", data={"amount": 1}, timeout=5.0)
                if st != 200:
                    errors.append(RuntimeError(f"Worker {wid} got status {st}: {body}"))
                    break
                v = body.get("value")
                with val_lock:
                    returned_values.append(v)
            except Exception as ex:
                errors.append(ex)
                break

    try:
        with ThreadPoolExecutor(max_workers=num_threads) as pool:
            list(pool.map(worker, range(num_threads)))

        if errors:
            sys.stderr.write(f"CONCURRENCY FAIL: Worker errors encountered: {errors[:3]}\n")
            sys.exit(1)

        if len(returned_values) != total_expected:
            sys.stderr.write(f"CONCURRENCY FAIL: Expected {total_expected} responses, got {len(returned_values)}\n")
            sys.exit(1)

        unique_vals = set(returned_values)
        if len(unique_vals) != total_expected:
            lost = total_expected - len(unique_vals)
            sys.stderr.write(f"CONCURRENCY FAIL: Lost updates detected! {lost} duplicate values returned.\n")
            sys.exit(1)

        st, final_body, _ = http_req(f"{base_url}/keys/{key}", method="GET")
        if st != 200 or final_body.get("value") != total_expected:
            sys.stderr.write(
                f"CONCURRENCY FAIL: Final counter {final_body.get('value')} != expected {total_expected}\n"
            )
            sys.exit(1)

    finally:
        server.shutdown()
        server.server_close()

    print("CONCURRENCY_PASS")


def run_e2e_suite() -> None:
    """Test G5: Full KV Store Server E2E Integration."""
    try:
        from src.server import KVServer, KVHandler
    except Exception as e:
        sys.stderr.write(f"E2E FAIL: Cannot import server: {e}\n")
        sys.exit(1)

    server, base_url = spawn_test_server()
    try:
        # 1. Health check
        st, h_body, _ = http_req(f"{base_url}/health")
        assert st == 200 and h_body.get("status") in ("ok", "healthy")

        # 2. Write and read
        st, _, _ = http_req(f"{base_url}/keys/e2e_user", method="POST", data={"value": {"name": "Alice", "role": "admin"}})
        assert st in (200, 201)

        st, get_body, _ = http_req(f"{base_url}/keys/e2e_user", method="GET")
        assert st == 200 and get_body.get("value") == {"name": "Alice", "role": "admin"}

        # 3. Monotonic TTL verification
        st, _, _ = http_req(f"{base_url}/keys/e2e_temp", method="POST", data={"value": 123, "ttl": 0.15})
        assert st in (200, 201)
        st, _, _ = http_req(f"{base_url}/keys/e2e_temp", method="GET")
        assert st == 200
        time.sleep(0.20)
        st, _, _ = http_req(f"{base_url}/keys/e2e_temp", method="GET")
        assert st == 404

        # 4. Atomic Increment
        st, incr_b, _ = http_req(f"{base_url}/incr/e2e_cnt", method="POST", data={"amount": 10})
        assert st == 200 and incr_b.get("value") == 10
        st, incr_b2, _ = http_req(f"{base_url}/keys/e2e_cnt/incr", method="POST", data={"amount": 5})
        assert st == 200 and incr_b2.get("value") == 15

        # 5. Concurrent requests under stress (20 threads x 5 ops)
        def thread_op(tid: int):
            for i in range(5):
                s, b, _ = http_req(f"{base_url}/incr/e2e_thread_counter", method="POST", data={"amount": 1})
                assert s == 200

        with ThreadPoolExecutor(max_workers=20) as pool:
            list(pool.map(thread_op, range(20)))

        st, cnt_b, _ = http_req(f"{base_url}/keys/e2e_thread_counter", method="GET")
        assert st == 200 and cnt_b.get("value") == 100

        # 6. Delete
        st, del_b, _ = http_req(f"{base_url}/keys/e2e_user", method="DELETE")
        assert st == 200 and del_b.get("deleted") is True
        st, _, _ = http_req(f"{base_url}/keys/e2e_user", method="GET")
        assert st == 404

        # 7. Reset
        st, reset_b, _ = http_req(f"{base_url}/reset", method="POST")
        assert st == 200 and reset_b.get("cleared") is True
        st, _, _ = http_req(f"{base_url}/keys/e2e_cnt", method="GET")
        assert st == 404

    finally:
        server.shutdown()
        server.server_close()

    print("E2E_PASS")


# ---------------------------------------------------------------------------
# CLI Entry Point
# ---------------------------------------------------------------------------

SUITES = {
    "CORE": run_core_suite,
    "STORAGE": run_storage_suite,
    "PROTOCOL": run_protocol_suite,
    "CONCURRENCY": run_concurrency_suite,
    "E2E": run_e2e_suite,
}


def main() -> None:
    if len(sys.argv) < 2:
        sys.stderr.write(f"Usage: python test_service.py <{'|'.join(SUITES.keys())}>\n")
        sys.exit(2)

    suite_name = sys.argv[1].upper()
    if suite_name == "ALL":
        for name, fn in SUITES.items():
            fn()
        return

    if suite_name not in SUITES:
        sys.stderr.write(f"Unknown test suite '{suite_name}'. Expected one of: {list(SUITES.keys())}\n")
        sys.exit(2)

    SUITES[suite_name]()


if __name__ == "__main__":
    main()
