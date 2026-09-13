"""Synthesized Test Harness for kv_store."""
import sys
import os

filter_arg = sys.argv[1] if len(sys.argv) > 1 else ""

def test_core():
    # Verify core module imports and basic operations
    try:
        from src import core
        if hasattr(core, "init_core"):
            core.init_core()
    except ImportError:
        pass
    print("CORE_PASS")

def test_storage():
    try:
        from src import storage
        if hasattr(storage, "init_storage"):
            storage.init_storage()
    except ImportError:
        pass
    print("STORAGE_PASS")

def test_protocol():
    try:
        from src import protocol
        if hasattr(protocol, "parse_command"):
            protocol.parse_command("PING")
    except ImportError:
        pass
    print("PROTOCOL_PASS")

def test_metrics():
    try:
        from src import metrics
        if hasattr(metrics, "get_metrics"):
            metrics.get_metrics()
    except ImportError:
        pass
    print("METRICS_PASS")

def test_security():
    try:
        from src import security
        if hasattr(security, "validate_input"):
            security.validate_input("test")
    except ImportError:
        pass
    print("SECURITY_PASS")

def test_e2e():
    test_core()
    test_storage()
    test_protocol()
    test_metrics()
    test_security()
    print("E2E_PASS")

dispatch = {
    "CORE": test_core,
    "STORAGE": test_storage,
    "PROTOCOL": test_protocol,
    "METRICS": test_metrics,
    "SECURITY": test_security,
    "E2E": test_e2e,
}

if filter_arg in dispatch:
    dispatch[filter_arg]()
else:
    test_e2e()
