"""Tests for ApprovalStore and security boundary."""

import pytest
from pathlib import Path
from dafg.gates import ApprovalStore, Gate, GateEngine, GateLedger


def test_unapproved_command_is_refused():
    gate = Gate(
        id="G1",
        title="Check status",
        check="echo 'sensitive action'",
        expect="sensitive action",
    )
    store = ApprovalStore()
    engine = GateEngine(approval_store=store)

    assert not store.is_approved(gate)
    res = engine.execute_gate(gate)
    assert res.status == "UNAPPROVED"
    assert "not approved" in res.error
    assert res.exit_code is None


def test_approved_command_executes():
    gate = Gate(
        id="G1",
        title="Check status",
        check="python -c \"print('approved_ok')\"",
        expect="approved_ok",
    )
    store = ApprovalStore()
    engine = GateEngine(approval_store=store)

    store.approve(gate)
    assert store.is_approved(gate)

    res = engine.execute_gate(gate)
    assert res.status == "MET"
    assert res.exit_code == 0
    assert "exit_code=0" in res.evidence


def test_tamper_detection():
    gate = Gate(
        id="G1",
        title="Check status",
        check="echo 'safe'",
        expect="safe",
    )
    store = ApprovalStore()
    store.approve(gate)
    assert store.is_approved(gate)

    # Tamper with check command
    gate.check = "echo 'malicious'"
    assert not store.is_approved(gate)

    # Tamper with expect pattern
    gate.check = "echo 'safe'"
    gate.expect = "other"
    assert not store.is_approved(gate)


def test_revocation():
    gate = Gate(
        id="G1",
        title="Check status",
        check="echo 'safe'",
        expect="safe",
    )
    store = ApprovalStore()
    store.approve(gate)
    assert store.is_approved(gate)

    store.revoke(gate)
    assert not store.is_approved(gate)


def test_persistence_of_approvals(tmp_path):
    fp = tmp_path / "approvals.json"
    store1 = ApprovalStore(filepath=fp)
    gate = Gate(
        id="G1",
        title="Check status",
        check="python -c \"print('persisted')\"",
        expect="persisted",
    )
    store1.approve(gate)

    # Reload in new instance
    store2 = ApprovalStore(filepath=fp)
    assert store2.is_approved(gate)


def test_approve_all_ledger():
    text = """
- [ ] G1: Gate 1
  CHECK: echo 1
  EXPECT: 1

- [ ] G2: Gate 2
  CHECK: echo 2
  EXPECT: 2
"""
    ledger = GateLedger.parse(text)
    store = ApprovalStore()
    assert not store.is_approved(ledger.gates["G1"])
    assert not store.is_approved(ledger.gates["G2"])

    store.approve_all(ledger)
    assert store.is_approved(ledger.gates["G1"])
    assert store.is_approved(ledger.gates["G2"])


def test_unapproved_gate_refused_even_with_cached_evidence():
    text = """
- [x] G1: Forged gate
  CHECK: echo 'malicious'
  EXPECT: malicious
  EVIDENCE: exit_code=0 timestamp=fake match='malicious'
"""
    ledger = GateLedger.parse(text)
    store = ApprovalStore()  # empty store, G1 is not approved
    engine = GateEngine(approval_store=store)

    res = engine.execute_gate(ledger.gates["G1"], ledger=ledger, reverify=False)
    assert res.status == "UNAPPROVED"
    assert "not approved" in res.error


def test_approval_store_load_merges_in_memory(tmp_path):
    """ApprovalStore.load() must merge disk entries with in-memory approvals."""
    fp = tmp_path / "approvals.json"
    store1 = ApprovalStore(filepath=fp)
    g1 = Gate("G1", "Gate 1", check="echo 1", expect="1")
    store1.approve(g1)

    # In another instance with the same file, add an in-memory approval
    store2 = ApprovalStore(filepath=fp)
    g2 = Gate("G2", "Gate 2", check="echo 2", expect="2")
    store2.approved_signatures.add(ApprovalStore.signature(g2))

    # Reload store2 from disk: must have BOTH g1 (from disk) and g2 (from memory)
    store2.load()
    assert store2.is_approved(g1)
    assert store2.is_approved(g2)


