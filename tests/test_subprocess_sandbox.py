"""Unit and integration tests for SubprocessSandbox OS containment boundary."""

import os
import pytest
import subprocess
from pathlib import Path
from dafg.sandbox import SubprocessSandbox, SandboxSecurityViolation
from dafg.gates import Gate, GateEngine, GateLedger


def test_sandbox_sanitizes_environment_and_removes_secrets(tmp_path):
    os.environ["AWS_SECRET_ACCESS_KEY"] = "super_secret_aws_key"
    os.environ["GITHUB_TOKEN"] = "ghp_1234567890abcdef"
    os.environ["DAFG_API_KEY"] = "dafg_secret_token"

    try:
        sandbox = SubprocessSandbox(workdir=tmp_path)
        clean_env = sandbox.build_sanitized_env()

        assert "AWS_SECRET_ACCESS_KEY" not in clean_env
        assert "GITHUB_TOKEN" not in clean_env
        assert "DAFG_API_KEY" not in clean_env
        assert "PATH" in clean_env
        assert "HOME" in clean_env
        assert str(tmp_path) in clean_env["HOME"]
    finally:
        os.environ.pop("AWS_SECRET_ACCESS_KEY", None)
        os.environ.pop("GITHUB_TOKEN", None)
        os.environ.pop("DAFG_API_KEY", None)


def test_sandbox_blocks_path_traversal_outside_workdir(tmp_path):
    sandbox = SubprocessSandbox(workdir=tmp_path)
    outside_dir = tmp_path.parent / "forbidden_external_dir"
    outside_dir.mkdir(parents=True, exist_ok=True)

    with pytest.raises(SandboxSecurityViolation) as exc_info:
        sandbox.run("echo test", cwd=outside_dir)

    assert "resolves outside sandbox root" in str(exc_info.value)


def test_sandbox_executes_safe_command_inside_workdir(tmp_path):
    sandbox = SubprocessSandbox(workdir=tmp_path)
    res = sandbox.run('python3 -c "print(\'contained_hello\')"')
    assert res.returncode == 0
    assert "contained_hello" in res.stdout


def test_sandbox_terminates_runaway_process_on_timeout(tmp_path):
    sandbox = SubprocessSandbox(workdir=tmp_path, timeout=0.3)
    with pytest.raises(TimeoutError):
        sandbox.run('python3 -c "import time; time.sleep(5)"')


def test_gate_engine_integrates_subprocess_sandbox(tmp_path):
    outside_dir = tmp_path.parent / "escape_dir"
    outside_dir.mkdir(parents=True, exist_ok=True)

    gate = Gate(
        id="G1",
        title="Sandbox Traversal Gate",
        check='python3 -c "print(\'ok\')"',
        expect="ok",
        cwd=str(outside_dir),
    )
    # Give ledger work_dir pointing to tmp_path
    ledger = GateLedger(work_dir=tmp_path)
    ledger.gates["G1"] = gate
    engine = GateEngine(auto_approve=True)
    res = engine.execute_gate(gate, ledger=ledger)
    assert res.status == "FAILED"
    assert "Sandbox containment violation" in res.error


def test_sandbox_blocks_ambient_code_loading_variables(tmp_path):
    os.environ["PYTHONPATH"] = "/malicious/python/path"
    os.environ["NODE_PATH"] = "/malicious/node/path"
    try:
        sandbox = SubprocessSandbox(workdir=tmp_path)
        clean_env = sandbox.build_sanitized_env()
        assert "PYTHONPATH" not in clean_env
        assert "NODE_PATH" not in clean_env
    finally:
        os.environ.pop("PYTHONPATH", None)
        os.environ.pop("NODE_PATH", None)


def test_sandbox_enforces_network_denial_by_default(tmp_path):
    sandbox = SubprocessSandbox(workdir=tmp_path, allow_network=False)
    clean_env = sandbox.build_sanitized_env()
    assert clean_env["HTTP_PROXY"] == "http://127.0.0.1:0"
    assert clean_env["HTTPS_PROXY"] == "http://127.0.0.1:0"
    assert clean_env["PIP_NO_INDEX"] == "1"


def test_sandbox_blocks_protected_os_paths(tmp_path):
    sandbox = SubprocessSandbox(workdir=tmp_path)
    with pytest.raises(SandboxSecurityViolation) as exc_info:
        sandbox.validate_target_path(Path("/proc/self/mem"))
    assert "protected OS hierarchy" in str(exc_info.value)

    with pytest.raises(SandboxSecurityViolation) as exc_info2:
        sandbox.validate_target_path(Path("/etc/passwd"))
    assert "protected OS hierarchy" in str(exc_info2.value)
