"""Tests for Closed-Loop Repair."""
from __future__ import annotations

import pytest
from dafg.repair import (
    RepairBudget,
    RepairDiagnoser,
    RepairLoop,
    RepairStatus,
    RepairResult,
    RepairAttempt,
)
from dafg.gates import GateLedger, GateEngine, GateResult


def test_repair_budget():
    b = RepairBudget(max_repair_attempts=2)
    assert b.can_attempt()
    b.consume()
    assert b.can_attempt()
    b.consume()
    assert not b.can_attempt()
    b.consume()
    assert not b.can_attempt()
    assert b.repair_attempts_consumed == 3


def test_repair_diagnoser():
    # NO_FAILURE
    res = GateResult(gate_id="G1", status="MET")
    assert RepairDiagnoser.diagnose(res) == "NO_FAILURE"

    # TIMEOUT
    res = GateResult(gate_id="G1", status="FAILED", error="Command timed out")
    assert RepairDiagnoser.diagnose(res) == "TIMEOUT"

    # EXIT_CODE
    res = GateResult(gate_id="G1", status="FAILED", exit_code=1)
    assert RepairDiagnoser.diagnose(res) == "EXIT_CODE_1"

    # OUTPUT_MISMATCH
    res = GateResult(gate_id="G1", status="FAILED", error="Output did not match expected")
    assert RepairDiagnoser.diagnose(res) == "OUTPUT_MISMATCH"

    # UNAPPROVED
    res = GateResult(gate_id="G1", status="UNAPPROVED", error="Execution refused unapproved")
    assert RepairDiagnoser.diagnose(res) == "UNAPPROVED"

    # EXECUTION_ERROR
    res = GateResult(gate_id="G1", status="FAILED", error="Exception occurred")
    assert RepairDiagnoser.diagnose(res) == "EXECUTION_ERROR"

    # UNKNOWN_FAILURE
    res = GateResult(gate_id="G1", status="FAILED", error="Something else")
    assert RepairDiagnoser.diagnose(res) == "UNKNOWN_FAILURE"


def test_repair_loop_already_passes(tmp_path):
    text = """
- [x] G1: title
  CHECK: echo hello
  EXPECT: hello
  EVIDENCE: exit_code=0
"""
    ledger = GateLedger.parse(text)
    engine = GateEngine(auto_approve=True)
    loop = RepairLoop(ledger=ledger, engine=engine)

    res = loop.repair_gate("G1")
    assert res.final_status == RepairStatus.REPAIRED
    assert res.attempts == 1
    assert res.attempt_history[0].diagnosis == "NO_FAILURE"


def test_repair_loop_always_fails_no_repair_fn(tmp_path):
    text = """
- [ ] G1: title
  CHECK: echo hello
  EXPECT: bye
"""
    ledger = GateLedger.parse(text)
    engine = GateEngine(auto_approve=True)
    loop = RepairLoop(ledger=ledger, engine=engine, budget=RepairBudget(1))

    res = loop.repair_gate("G1")
    assert res.final_status == RepairStatus.BUDGET_EXHAUSTED
    assert res.attempts == 1
    assert res.attempt_history[0].post_status == "FAILED"


def test_repair_loop_fails_then_passes(tmp_path):
    text = """
- [ ] G1: title
  CHECK: cat out.txt
  EXPECT: fixed
"""
    ledger = GateLedger.parse(text)
    engine = GateEngine(auto_approve=True)
    
    (tmp_path / "out.txt").write_text("broken")
    for g in ledger.gates.values():
        g.cwd = str(tmp_path)

    def my_repair(gid, diag, check):
        (tmp_path / "out.txt").write_text("fixed")
        return "wrote fixed"

    loop = RepairLoop(ledger=ledger, engine=engine, repair_fn=my_repair)
    res = loop.repair_gate("G1")
    
    assert res.final_status == RepairStatus.REPAIRED
    assert res.attempts == 1
    assert res.attempt_history[0].post_status == "MET"


def test_repair_loop_abandoned(tmp_path):
    text = """
- [-] G1: title
  ABANDON: reason
  CHECK: echo 1
  EXPECT: 1
"""
    ledger = GateLedger.parse(text)
    engine = GateEngine(auto_approve=True)
    loop = RepairLoop(ledger=ledger, engine=engine)
    res = loop.repair_gate("G1")
    assert res.final_status == RepairStatus.SKIPPED


def test_repair_loop_no_check(tmp_path):
    text = """
- [ ] G1: title
"""
    ledger = GateLedger.parse(text)
    engine = GateEngine(auto_approve=True)
    loop = RepairLoop(ledger=ledger, engine=engine)
    res = loop.repair_gate("G1")
    assert res.final_status == RepairStatus.SKIPPED


def test_repair_loop_nonexistent(tmp_path):
    ledger = GateLedger.parse("")
    engine = GateEngine(auto_approve=True)
    loop = RepairLoop(ledger=ledger, engine=engine)
    res = loop.repair_gate("G1")
    assert res.final_status == RepairStatus.SKIPPED


def test_repair_loop_budget_enforcement(tmp_path):
    text = """
- [ ] G1: title
  CHECK: echo hello
  EXPECT: bye
"""
    ledger = GateLedger.parse(text)
    engine = GateEngine(auto_approve=True)
    loop = RepairLoop(ledger=ledger, engine=engine, budget=RepairBudget(1))
    res = loop.repair_gate("G1")
    assert res.attempts == 1
    assert res.final_status == RepairStatus.BUDGET_EXHAUSTED


def test_repair_loop_attempt_history(tmp_path):
    text = """
- [ ] G1: title
  CHECK: echo hello
  EXPECT: bye
"""
    ledger = GateLedger.parse(text)
    engine = GateEngine(auto_approve=True)
    loop = RepairLoop(ledger=ledger, engine=engine, budget=RepairBudget(1))
    res = loop.repair_gate("G1")
    hist = res.attempt_history[0]
    assert hist.attempt_num == 1
    assert hist.diagnosis == "OUTPUT_MISMATCH"
    assert hist.patch_description == "no repair function provided"


def test_repair_result_to_dict():
    attempt = RepairAttempt(
        attempt_num=1,
        diagnosis="NO_FAILURE",
        patch_description="none",
        pre_status="UNMET",
        post_status="MET",
        duration_ms=10.0
    )
    res = RepairResult(
        gate_id="G1",
        final_status=RepairStatus.REPAIRED,
        attempts=1,
        attempt_history=[attempt],
        budget_consumed=1
    )
    d = res.to_dict()
    assert d["gate_id"] == "G1"
    assert d["final_status"] == RepairStatus.REPAIRED
    assert d["attempt_history"][0]["diagnosis"] == "NO_FAILURE"


def test_repair_all_failing(tmp_path):
    text = """
- [x] G1: title
  CHECK: echo 1
  EXPECT: 1
  EVIDENCE: exit_code=0
- [ ] G2: title
  CHECK: echo 2
  EXPECT: 3
- [-] G3: title
  CHECK: echo 3
  EXPECT: 3
  ABANDON: yes
"""
    ledger = GateLedger.parse(text)
    engine = GateEngine(auto_approve=True)
    loop = RepairLoop(ledger=ledger, engine=engine, budget=RepairBudget(1))
    results = loop.repair_all_failing()
    
    assert "G2" in results
    assert "G1" not in results
    assert "G3" not in results
    assert results["G2"].final_status == RepairStatus.BUDGET_EXHAUSTED


def test_repair_loop_exception_in_repair_fn(tmp_path):
    text = """
- [ ] G1: title
  CHECK: echo hello
  EXPECT: bye
"""
    ledger = GateLedger.parse(text)
    engine = GateEngine(auto_approve=True)
    
    def bad_repair(*args):
        raise ValueError("Oops")
        
    loop = RepairLoop(ledger=ledger, engine=engine, repair_fn=bad_repair, budget=RepairBudget(1))
    res = loop.repair_gate("G1")
    assert res.final_status == RepairStatus.BUDGET_EXHAUSTED
    assert "repair error: Oops" in res.attempt_history[0].patch_description
