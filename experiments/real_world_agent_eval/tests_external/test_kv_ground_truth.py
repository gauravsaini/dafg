"""Independent adversarial ground-truth test suite for in-memory KV store server benchmark.

Completely isolated from DAFG internal gates, OrganismGenesis, and implementing agents.
Executes real HTTP requests over live TCP sockets asserting on status codes, JSON response bodies,
monotonic TTL expiry timing, and high-concurrency atomic updates.
"""
from __future__ import annotations

import json
import random
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, Optional, Tuple

import pytest


# ---------------------------------------------------------------------------
# Standard Library HTTP Client Helper & Route Resolution
# ---------------------------------------------------------------------------

def http_request(
    url: str,
    method: str = "GET",
    data: Optional[Any] = None,
    payload: Optional[Any] = None,
    raw_body: Optional[bytes] = None,
    headers: Optional[Dict[str, str]] = None,
    timeout: float = 5.0,
    retries: int = 2,
    backoff_sec: float = 0.05,
) -> Tuple[int, Any, Dict[str, str]]:
    """Execute an HTTP request using Python standard library urllib.request.

    Handles 2xx responses and 4xx/5xx HTTPError responses uniformly, returning
    (status_code, parsed_json_or_text, headers_dict).
    """
    if payload is not None and data is None:
        data = payload

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
    attempts = 0
    while True:
        attempts += 1
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw_resp = resp.read()
                resp_hdrs = dict(resp.headers)
                try:
                    payload_out = json.loads(raw_resp.decode("utf-8"))
                except Exception:
                    payload_out = raw_resp.decode("utf-8", errors="replace")
                return resp.status, payload_out, resp_hdrs
        except urllib.error.HTTPError as err:
            raw_resp = err.read()
            resp_hdrs = dict(err.headers)
            try:
                payload_out = json.loads(raw_resp.decode("utf-8"))
            except Exception:
                payload_out = raw_resp.decode("utf-8", errors="replace")
            return err.code, payload_out, resp_hdrs
        except (urllib.error.URLError, TimeoutError, ConnectionResetError, OSError):
            if attempts <= retries and method.upper() not in ("POST", "PUT"):
                time.sleep(backoff_sec * attempts)
                continue
            raise


_INCR_ROUTE_PREFIX: Optional[str] = None


def get_incr_endpoint(base_url: str, key: str) -> str:
    """Resolve whether the server mounts /incr/{key} or /keys/{key}/incr."""
    global _INCR_ROUTE_PREFIX
    if _INCR_ROUTE_PREFIX is None:
        probe_key = "__probe_incr_route__"
        url1 = f"{base_url}/incr/{probe_key}"
        s, _, _ = http_request(url1, method="POST", data={"amount": 0}, timeout=2.0)
        if s == 200:
            _INCR_ROUTE_PREFIX = "/incr"
            http_request(f"{base_url}/keys/{probe_key}", method="DELETE", timeout=2.0)
        else:
            _INCR_ROUTE_PREFIX = "/keys"

    if _INCR_ROUTE_PREFIX == "/incr":
        return f"{base_url}/incr/{key}"
    return f"{base_url}/keys/{key}/incr"


# ---------------------------------------------------------------------------
# 1. CRUD Operations & Basic Data Types (7 Tests)
# ---------------------------------------------------------------------------

def test_set_and_get_basic_string(kv_server: str) -> None:
    """Verify basic key storage and retrieval for string values."""
    url = f"{kv_server}/keys/test_string_key"
    status, body, headers = http_request(url, method="POST", data={"value": "hello_world"})
    assert status in (200, 201), f"Expected 200 or 201 on POST, got {status}: {body}"
    assert "application/json" in headers.get("Content-Type", "")
    assert isinstance(body, dict)
    assert body.get("status") == "ok" or body.get("key") == "test_string_key"
    assert body.get("value") == "hello_world"

    status, body, headers = http_request(url, method="GET")
    assert status == 200, f"Expected 200 on GET, got {status}: {body}"
    assert "application/json" in headers.get("Content-Type", "")
    assert isinstance(body, dict)
    assert body.get("key") == "test_string_key"
    assert body.get("value") == "hello_world"
    assert body.get("ttl") is None


def test_get_nonexistent_key_returns_404(kv_server: str) -> None:
    """Verify that requesting a key that does not exist returns HTTP 404 Not Found."""
    url = f"{kv_server}/keys/definitely_missing_key_99999"
    status, body, headers = http_request(url, method="GET")
    assert status == 404, f"Expected 404 for missing key, got {status}: {body}"
    assert "application/json" in headers.get("Content-Type", "")
    assert isinstance(body, dict)
    assert "error" in body
    assert (
        "definitely_missing_key_99999" in str(body.get("key", ""))
        or "not found" in str(body.get("error", "")).lower()
    )


def test_set_overwrite_existing_key(kv_server: str) -> None:
    """Verify that writing to an existing key overwrites the stored value."""
    url = f"{kv_server}/keys/overwrite_target_key"
    status, body, _ = http_request(url, method="POST", data={"value": "initial_val"})
    assert status in (200, 201)

    status, body, _ = http_request(url, method="GET")
    assert status == 200 and body.get("value") == "initial_val"

    status, body, _ = http_request(url, method="POST", data={"value": "updated_val"})
    assert status in (200, 201)

    status, body, _ = http_request(url, method="GET")
    assert status == 200 and body.get("value") == "updated_val"


def test_store_complex_json_types(kv_server: str) -> None:
    """Verify storage and retrieval of diverse valid JSON types."""
    cases = {
        "int_key": 424242,
        "float_key": 3.1415926535,
        "bool_true_key": True,
        "bool_false_key": False,
        "list_key": [1, "two", 3.0, {"nested": True}, None],
        "dict_key": {
            "user_id": 101,
            "roles": ["admin", "developer"],
            "active": True,
            "profile": {"display_name": "Ada", "scores": [98, 99, 100]},
        },
    }

    for key, expected_value in cases.items():
        url = f"{kv_server}/keys/{key}"
        status, _, _ = http_request(url, method="POST", data={"value": expected_value})
        assert status in (200, 201), f"Failed to store {key}: {expected_value}"

        status, body, _ = http_request(url, method="GET")
        assert status == 200, f"Failed to retrieve {key}"
        assert body.get("value") == expected_value, (
            f"Type/value mismatch for {key}: {body.get('value')} != {expected_value}"
        )


def test_null_value_distinct_from_missing_key(kv_server: str) -> None:
    """Verify that storing a JSON null value is explicitly distinguished from a missing key."""
    url = f"{kv_server}/keys/explicit_null_key"
    status, body, _ = http_request(url, method="POST", data={"value": None})
    assert status in (200, 201)

    status, body, _ = http_request(url, method="GET")
    assert status == 200, f"Stored null key must return 200 OK, got {status}: {body}"
    assert body.get("key") == "explicit_null_key"
    assert body.get("value") is None
    assert "value" in body

    status_missing, _, _ = http_request(f"{kv_server}/keys/actual_nonexistent_key", method="GET")
    assert status_missing == 404


def test_delete_existing_key(kv_server: str) -> None:
    """Verify deletion of an existing key."""
    url = f"{kv_server}/keys/key_to_delete"
    status, _, _ = http_request(url, method="POST", data={"value": "delete_me"})
    assert status in (200, 201)

    status, body, headers = http_request(url, method="DELETE")
    assert status == 200, f"Expected 200 on DELETE, got {status}: {body}"
    assert "application/json" in headers.get("Content-Type", "")
    assert isinstance(body, dict)
    assert body.get("status") == "ok"
    assert body.get("deleted") is True

    status, body, _ = http_request(url, method="GET")
    assert status == 404, f"Deleted key must return 404, got {status}: {body}"


def test_delete_nonexistent_key_returns_404(kv_server: str) -> None:
    """Verify that deleting a non-existent key returns HTTP 404 Not Found."""
    url = f"{kv_server}/keys/nonexistent_delete_target"
    status, body, headers = http_request(url, method="DELETE")
    assert status == 404, f"Expected 404 on deleting missing key, got {status}: {body}"
    assert "application/json" in headers.get("Content-Type", "")
    assert isinstance(body, dict)
    assert "error" in body


# ---------------------------------------------------------------------------
# 2. Monotonic TTL Expiry Lifecycle (4 Tests)
# ---------------------------------------------------------------------------

def test_ttl_expiration_after_sleep(kv_server: str) -> None:
    """Verify monotonic TTL expiration of stored keys."""
    url = f"{kv_server}/keys/ephemeral_test_key"
    status, body, _ = http_request(url, method="POST", data={"value": "ephemeral_val", "ttl": 0.2})
    assert status in (200, 201)

    status, body, _ = http_request(url, method="GET")
    assert status == 200, f"Expected 200 immediately after set, got {status}"
    assert body.get("value") == "ephemeral_val"
    rem_ttl = body.get("ttl")
    assert rem_ttl is not None and 0.0 < rem_ttl <= 0.25, f"Expected 0 < ttl <= 0.25, got {rem_ttl}"

    time.sleep(0.25)

    status, body, _ = http_request(url, method="GET")
    assert status == 404, f"Expected 404 after TTL expiration, got {status}: {body}"

    status, body, _ = http_request(url, method="DELETE")
    assert status == 404, f"Expected 404 deleting expired key, got {status}: {body}"


def test_ttl_cleared_by_subsequent_set_without_ttl(kv_server: str) -> None:
    """Verify that overwriting a key without specifying TTL clears the expiration timer."""
    url = f"{kv_server}/keys/ttl_reset_key"
    status, _, _ = http_request(url, method="POST", data={"value": "val1", "ttl": 0.15})
    assert status in (200, 201)

    status, body, _ = http_request(url, method="POST", data={"value": "val2"})
    assert status in (200, 201)

    time.sleep(0.20)

    status, body, _ = http_request(url, method="GET")
    assert status == 200, f"Expected key to persist after timer cleared, got {status}: {body}"
    assert body.get("value") == "val2"
    assert body.get("ttl") is None


def test_ttl_extension_on_subsequent_set(kv_server: str) -> None:
    """Verify extending the TTL of an existing key via subsequent POST."""
    url = f"{kv_server}/keys/ttl_extension_key"
    status, _, _ = http_request(url, method="POST", data={"value": "short_lived", "ttl": 0.15})
    assert status in (200, 201)

    status, _, _ = http_request(url, method="POST", data={"value": "extended_life", "ttl": 0.50})
    assert status in (200, 201)

    time.sleep(0.20)

    status, body, _ = http_request(url, method="GET")
    assert status == 200, f"Expected key to remain valid after TTL extension, got {status}: {body}"
    assert body.get("value") == "extended_life"
    rem_ttl = body.get("ttl")
    assert rem_ttl is not None and rem_ttl > 0.1, f"Expected remaining TTL > 0.1, got {rem_ttl}"


def test_negative_and_zero_ttl_returns_400(kv_server: str) -> None:
    """Verify that zero, negative, or invalid TTL values return HTTP 400 Bad Request."""
    invalid_ttls = [0, -1, -5.5, "10s", True]
    for bad_ttl in invalid_ttls:
        key = f"bad_ttl_key_{bad_ttl}"
        url = f"{kv_server}/keys/{key}"
        status, body, headers = http_request(url, method="POST", data={"value": "test", "ttl": bad_ttl})
        assert status == 400, f"Expected 400 for ttl={bad_ttl}, got {status}: {body}"
        assert "application/json" in headers.get("Content-Type", "")
        assert "error" in body

        get_status, _, _ = http_request(url, method="GET")
        assert get_status == 404, f"Key with invalid TTL must not exist, got {get_status}"


# ---------------------------------------------------------------------------
# 3. HTTP Error Handling & Framing Conformance (5 Tests)
# ---------------------------------------------------------------------------

def test_invalid_json_payload_returns_400(kv_server: str) -> None:
    """Verify that sending malformed JSON in a POST request returns HTTP 400 Bad Request."""
    url = f"{kv_server}/keys/malformed_json_key"
    raw_bad_json = b'{"value": "unclosed string, 123'
    status, body, headers = http_request(url, method="POST", raw_body=raw_bad_json)
    assert status == 400, f"Expected 400 Bad Request on malformed JSON, got {status}: {body}"
    assert "application/json" in headers.get("Content-Type", "")
    assert isinstance(body, dict)
    assert "error" in body


def test_missing_value_field_in_post_returns_400(kv_server: str) -> None:
    """Verify that POST /keys/{key} without a required 'value' field returns HTTP 400 Bad Request."""
    url = f"{kv_server}/keys/missing_value_key"
    status, body, headers = http_request(url, method="POST", data={"ttl": 10})
    assert status == 400, f"Expected 400 Bad Request when 'value' is missing, got {status}: {body}"
    assert "application/json" in headers.get("Content-Type", "")
    assert isinstance(body, dict)
    assert "error" in body
    assert "value" in str(body.get("error", "")).lower()


def test_empty_post_body_returns_400(kv_server: str) -> None:
    """Verify that sending an empty POST body to /keys/{key} returns HTTP 400 Bad Request."""
    url = f"{kv_server}/keys/empty_body_key"
    status, body, headers = http_request(url, method="POST", raw_body=b"")
    assert status == 400, f"Expected 400 on empty POST body, got {status}: {body}"
    assert "application/json" in headers.get("Content-Type", "")
    assert "error" in body


def test_url_percent_encoding_special_characters(kv_server: str) -> None:
    """Verify URL percent-encoding roundtrip for special characters in key names."""
    test_keys = [
        "user:101:profile",
        "folder/subfolder/document.txt",
        "key with spaces in name",
        "metric.cpu-usage+load@host",
        "greeting:\U0001f389:rocket:\U0001f680",
    ]

    for original_key in test_keys:
        quoted_key = urllib.parse.quote(original_key, safe="")
        url = f"{kv_server}/keys/{quoted_key}"
        stored_value = f"val_for_{original_key}"

        status, post_body, _ = http_request(url, method="POST", data={"value": stored_value})
        assert status in (200, 201), f"Failed storing encoded key '{original_key}' via '{quoted_key}'"
        assert post_body.get("key") == original_key or post_body.get("status") == "ok"

        status, get_body, _ = http_request(url, method="GET")
        assert status == 200, f"Failed retrieving encoded key '{original_key}' via '{quoted_key}'"
        assert get_body.get("key") == original_key, f"Expected key '{original_key}', got '{get_body.get('key')}'"
        assert get_body.get("value") == stored_value

        status, del_body, _ = http_request(url, method="DELETE")
        assert status == 200, f"Failed deleting encoded key '{original_key}'"
        assert del_body.get("deleted") is True


def test_http_response_headers_and_framing(kv_server: str) -> None:
    """Verify that all responses (2xx, 4xx) include correct HTTP framing headers."""
    status, _, headers = http_request(f"{kv_server}/keys/hdr_check", method="POST", data={"value": "test"})
    assert "application/json" in headers.get("Content-Type", "")
    assert "Content-Length" in headers
    assert int(headers["Content-Length"]) > 0

    status, _, headers = http_request(f"{kv_server}/keys/hdr_check", method="GET")
    assert "application/json" in headers.get("Content-Type", "")
    assert "Content-Length" in headers
    assert int(headers["Content-Length"]) > 0

    status, _, headers = http_request(f"{kv_server}/keys/hdr_missing_key", method="GET")
    assert status == 404
    assert "application/json" in headers.get("Content-Type", "")
    assert "Content-Length" in headers
    assert int(headers["Content-Length"]) > 0

    status, _, headers = http_request(f"{kv_server}/keys/hdr_bad", method="POST", raw_body=b"bad_json")
    assert status == 400
    assert "application/json" in headers.get("Content-Type", "")
    assert "Content-Length" in headers
    assert int(headers["Content-Length"]) > 0


# ---------------------------------------------------------------------------
# 4. State Isolation (1 Test)
# ---------------------------------------------------------------------------

def test_reset_endpoint_clears_all_data(kv_server: str) -> None:
    """Verify that POST /reset wipes all keys and expiration timers."""
    for i in range(5):
        http_request(f"{kv_server}/keys/reset_test_k{i}", method="POST", data={"value": f"val{i}"})

    status, body, headers = http_request(f"{kv_server}/reset", method="POST")
    assert status == 200, f"Expected 200 on /reset, got {status}: {body}"
    assert "application/json" in headers.get("Content-Type", "")
    assert body.get("status") == "ok"
    assert body.get("cleared") is True

    for i in range(5):
        get_status, _, _ = http_request(f"{kv_server}/keys/reset_test_k{i}", method="GET")
        assert get_status == 404, f"Key reset_test_k{i} should return 404 after reset, got {get_status}"


# ---------------------------------------------------------------------------
# 5. Adversarial Concurrency & Contention (3 Tests)
# ---------------------------------------------------------------------------

def test_concurrent_atomic_increments_no_lost_updates(kv_server: str) -> None:
    """50 concurrent worker threads executing 10 atomic increments each."""
    key = "concurrent_counter_test"
    num_workers = 50
    increments_per_worker = 10
    total_expected = num_workers * increments_per_worker

    http_request(f"{kv_server}/keys/{key}", method="DELETE")
    incr_url = get_incr_endpoint(kv_server, key)

    barrier = threading.Barrier(num_workers)
    worker_errors = []

    def increment_worker(worker_id: int):
        barrier.wait()
        worker_returned_values = []
        for _ in range(increments_per_worker):
            try:
                status, body, _ = http_request(
                    incr_url,
                    method="POST",
                    data={"amount": 1},
                    timeout=5.0,
                )
                assert status == 200, f"Worker {worker_id} got status {status}: {body}"
                val = body.get("value")
                assert isinstance(val, int), f"Worker {worker_id} received non-integer value: {val}"
                worker_returned_values.append(val)
            except Exception as ex:
                worker_errors.append((worker_id, ex))
                break
        return worker_returned_values

    with ThreadPoolExecutor(max_workers=num_workers) as executor:
        results = list(executor.map(increment_worker, range(num_workers)))

    assert len(worker_errors) == 0, f"Worker errors encountered: {worker_errors[:5]}"

    all_returned_values = [v for worker_vals in results for v in worker_vals]
    assert len(all_returned_values) == total_expected, (
        f"Expected {total_expected} responses, got {len(all_returned_values)}"
    )

    unique_returned_values = set(all_returned_values)
    assert len(unique_returned_values) == total_expected, (
        f"Lost updates detected! {total_expected - len(unique_returned_values)} duplicate values returned."
    )
    assert unique_returned_values == set(range(1, total_expected + 1)), (
        "Returned counter values did not match the expected contiguous sequence 1..500."
    )

    get_status, get_body, _ = http_request(f"{kv_server}/keys/{key}", method="GET")
    assert get_status == 200
    assert get_body.get("value") == total_expected, (
        f"Final counter is {get_body.get('value')}, expected {total_expected}!"
    )


def test_concurrent_atomic_increments_arbitrary_amounts(kv_server: str) -> None:
    """50 concurrent worker threads executing increments with varying positive & negative deltas."""
    key = "arbitrary_deltas_counter"
    num_workers = 50
    http_request(f"{kv_server}/keys/{key}", method="DELETE")

    init_status, _, _ = http_request(f"{kv_server}/keys/{key}", method="POST", data={"value": 1000})
    assert init_status in (200, 201)

    incr_url = get_incr_endpoint(kv_server, key)
    barrier = threading.Barrier(num_workers)
    worker_errors = []

    def worker_delta(wid: int):
        barrier.wait()
        try:
            s1, _, _ = http_request(incr_url, method="POST", data={"amount": wid + 1}, timeout=5.0)
            assert s1 == 200
            s2, _, _ = http_request(incr_url, method="POST", data={"amount": -wid}, timeout=5.0)
            assert s2 == 200
        except Exception as ex:
            worker_errors.append((wid, ex))

    with ThreadPoolExecutor(max_workers=num_workers) as executor:
        list(executor.map(worker_delta, range(num_workers)))

    assert len(worker_errors) == 0, f"Worker errors: {worker_errors[:5]}"

    get_status, get_body, _ = http_request(f"{kv_server}/keys/{key}", method="GET")
    assert get_status == 200
    assert get_body.get("value") == 1050, f"Expected 1050, got {get_body.get('value')}"


def test_concurrent_read_write_delete_contention(kv_server: str) -> None:
    """50 concurrent threads executing 1,000 mixed operations under extreme contention."""
    num_workers = 50
    ops_per_worker = 20
    shared_key = "hot_contention_key"
    counter_key = "storm_counter_key"

    http_request(f"{kv_server}/keys/{shared_key}", method="POST", data={"value": "initial"})
    http_request(f"{kv_server}/keys/{counter_key}", method="POST", data={"value": 0})
    counter_incr_url = get_incr_endpoint(kv_server, counter_key)

    barrier = threading.Barrier(num_workers)
    operation_errors = []

    def storm_worker(worker_id: int):
        barrier.wait()
        for op_idx in range(ops_per_worker):
            try:
                dice = random.random()
                if dice < 0.25:
                    status, body, _ = http_request(
                        f"{kv_server}/keys/{shared_key}",
                        method="POST",
                        data={"value": f"worker_{worker_id}_{op_idx}"},
                        timeout=5.0,
                    )
                    assert status in (200, 201), f"Write returned invalid status {status}: {body}"
                elif dice < 0.50:
                    status, body, _ = http_request(f"{kv_server}/keys/{shared_key}", method="GET", timeout=5.0)
                    assert status in (200, 404), f"Read returned invalid status {status}: {body}"
                    if status == 200:
                        assert "value" in body
                elif dice < 0.65:
                    status, body, _ = http_request(f"{kv_server}/keys/{shared_key}", method="DELETE", timeout=5.0)
                    assert status in (200, 404), f"Delete returned invalid status {status}: {body}"
                elif dice < 0.85:
                    p_key = f"worker_private_{worker_id}"
                    s_write, _, _ = http_request(
                        f"{kv_server}/keys/{p_key}",
                        method="POST",
                        data={"value": op_idx},
                        timeout=5.0,
                    )
                    assert s_write in (200, 201)
                    s_read, b_read, _ = http_request(f"{kv_server}/keys/{p_key}", method="GET", timeout=5.0)
                    assert s_read == 200
                    assert b_read.get("value") == op_idx
                else:
                    status, body, _ = http_request(
                        counter_incr_url,
                        method="POST",
                        data={"amount": 1},
                        timeout=5.0,
                    )
                    assert status == 200, f"Increment returned invalid status {status}: {body}"
                    assert isinstance(body.get("value"), int)
            except Exception as ex:
                operation_errors.append((worker_id, op_idx, ex))
                break

    with ThreadPoolExecutor(max_workers=num_workers) as executor:
        list(executor.map(storm_worker, range(num_workers)))

    assert len(operation_errors) == 0, f"Encountered {len(operation_errors)} errors in storm: {operation_errors[:5]}"

    health_status, health_body, _ = http_request(f"{kv_server}/health", method="GET")
    assert health_status == 200, f"Server degraded after storm: {health_status}, {health_body}"
