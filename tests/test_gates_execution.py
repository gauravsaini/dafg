"""Tests for GateEngine execution, evidence generation, and reverification."""

import pytest
from pathlib import Path
from dafg.gates import Gate, GateEngine, GateLedger


def test_successful_execution_records_evidence(tmp_path):
    text = """
- [ ] G1: Echo check
  CHECK: python -c "print('everything is fine')"
  EXPECT: everything is fine
"""
    fp = tmp_path / "GATES.md"
    fp.write_text(text, encoding="utf-8")
    ledger = GateLedger.load(fp)

    engine = GateEngine(auto_approve=True)
    res = engine.execute_gate(ledger.gates["G1"], ledger=ledger)

    assert res.status == "MET"
    assert res.exit_code == 0
    assert "exit_code=0" in res.evidence
    assert "everything is fine" in res.evidence

    # Check updated markdown
    content = fp.read_text(encoding="utf-8")
    assert "- [x] G1: Echo check" in content
    assert "EVIDENCE: exit_code=0" in content


def test_failed_exit_code():
    gate = Gate(
        id="G1",
        title="Failing exit code",
        check="python -c \"import sys; sys.exit(2)\"",
        expect="fine",
    )
    engine = GateEngine(auto_approve=True)
    res = engine.execute_gate(gate)

    assert res.status == "FAILED"
    assert res.exit_code == 2
    assert "exit code 2" in res.error


def test_failed_expect_match():
    gate = Gate(
        id="G1",
        title="Mismatching output",
        check="python -c \"print('goodbye')\"",
        expect="hello",
    )
    engine = GateEngine(auto_approve=True)
    res = engine.execute_gate(gate)

    assert res.status == "FAILED"
    assert res.exit_code == 0
    assert "did not match EXPECT" in res.error


def test_timeout_handling():
    gate = Gate(
        id="G1",
        title="Sleep command",
        check="python -c \"import time; time.sleep(2)\"",
        expect="done",
    )
    engine = GateEngine(auto_approve=True, timeout=0.1)
    res = engine.execute_gate(gate)

    assert res.status == "FAILED"
    assert "timed out" in res.error


def test_reverification_demotes_when_condition_breaks(tmp_path):
    # Initially gate was marked MET
    text = """
- [x] G1: File check
  CHECK: python -c "import os; exit(0 if os.path.exists('flag.txt') else 1)"
  EXPECT: .*
  EVIDENCE: exit_code=0 timestamp=2026-09-10T12:00:00Z match=''
"""
    fp = tmp_path / "GATES.md"
    fp.write_text(text, encoding="utf-8")
    ledger = GateLedger.load(fp)

    # In tmp_path, flag.txt does NOT exist -> should fail
    engine = GateEngine(auto_approve=True)
    res = engine.execute_gate(ledger.gates["G1"], ledger=ledger, reverify=True, cwd_override=tmp_path)

    assert res.status == "FAILED"
    assert ledger.gates["G1"].status == "UNMET"
    assert ledger.gates["G1"].evidence is None

    # Check updated markdown: checkbox should be [ ]
    content = fp.read_text(encoding="utf-8")
    assert "- [ ] G1: File check" in content


def test_gate_specific_timeout():
    gate = Gate(
        id="G_timeout",
        title="Gate with custom timeout",
        check="python -c \"import time; time.sleep(0.5)\"",
        expect="done",
        timeout=0.1,
    )
    engine = GateEngine(auto_approve=True, timeout=10.0)
    res = engine.execute_gate(gate)
    assert res.status == "FAILED"
    assert "timed out after 0.1s" in res.error


def test_reverification_demotes_on_timeout(tmp_path):
    text = """
- [x] G1: Sleep gate
  CHECK: python -c "import time; time.sleep(2)"
  EXPECT: done
  TIMEOUT: 0.1
  EVIDENCE: exit_code=0 timestamp=2026-09-10T12:00:00Z match=''
"""
    fp = tmp_path / "GATES.md"
    fp.write_text(text, encoding="utf-8")
    ledger = GateLedger.load(fp)

    engine = GateEngine(auto_approve=True)
    res = engine.execute_gate(ledger.gates["G1"], ledger=ledger, reverify=True)

    assert res.status == "FAILED"
    assert ledger.gates["G1"].status == "UNMET"
    assert ledger.gates["G1"].evidence is None
    content = fp.read_text(encoding="utf-8")
    assert "- [ ] G1: Sleep gate" in content


def test_reverification_demotes_on_exception(tmp_path):
    text = """
- [x] G1: Crash gate
  CHECK: python -c "print('ok')"
  EXPECT: ok
  CWD: nonexistent_dir_12345
  EVIDENCE: exit_code=0 timestamp=2026-09-10T12:00:00Z match=''
"""
    fp = tmp_path / "GATES.md"
    fp.write_text(text, encoding="utf-8")
    ledger = GateLedger.load(fp)

    engine = GateEngine(auto_approve=True)
    res = engine.execute_gate(ledger.gates["G1"], ledger=ledger, reverify=True)

    assert res.status == "FAILED"
    assert ledger.gates["G1"].status == "UNMET"
    assert ledger.gates["G1"].evidence is None
    content = fp.read_text(encoding="utf-8")
    assert "- [ ] G1: Crash gate" in content


def test_execute_demotes_on_failure_when_reverify_false(tmp_path):
    text = """
- [x] G1: Failing gate with pending evidence
  CHECK: python -c "import sys; sys.exit(1)"
  EXPECT: ok
  EVIDENCE: pending
"""
    fp = tmp_path / "GATES.md"
    fp.write_text(text, encoding="utf-8")
    ledger = GateLedger.load(fp)

    engine = GateEngine(auto_approve=True)
    res = engine.execute_gate(ledger.gates["G1"], ledger=ledger, reverify=False)

    assert res.status == "FAILED"
    assert ledger.gates["G1"].status == "UNMET"
    assert ledger.gates["G1"].evidence is None
    content = fp.read_text(encoding="utf-8")
    assert "- [ ] G1: Failing gate with pending evidence" in content


def test_allow_regression_false_preserves_evidence(tmp_path):
    text = """
- [x] G1: Historical gate
  CHECK: python -c "import sys; sys.exit(1)"
  EXPECT: ok
  EVIDENCE: exit_code=0 timestamp=2026-09-10T12:00:00Z match=''
"""
    fp = tmp_path / "GATES.md"
    fp.write_text(text, encoding="utf-8")
    ledger = GateLedger.load(fp)

    engine = GateEngine(auto_approve=True, allow_regression=False)
    res = engine.execute_gate(ledger.gates["G1"], ledger=ledger, reverify=True)

    assert res.status == "FAILED"
    # Evidence must NOT be stripped when allow_regression=False
    assert ledger.gates["G1"].status == "MET"
    assert ledger.gates["G1"].evidence is not None
    content = fp.read_text(encoding="utf-8")
    assert "- [x] G1: Historical gate" in content


def test_environment_dependency_error_returns_blocked(tmp_path):
    text = """
- [ ] G1: Missing module gate
  CHECK: python -c "raise ModuleNotFoundError('No module named foo_bar_baz')"
  EXPECT: ok
"""
    fp = tmp_path / "GATES.md"
    fp.write_text(text, encoding="utf-8")
    ledger = GateLedger.load(fp)

    engine = GateEngine(auto_approve=True)
    res = engine.execute_gate(ledger.gates["G1"], ledger=ledger, reverify=True)

    assert res.status == "BLOCKED"
    assert "Environment dependency error" in res.error

