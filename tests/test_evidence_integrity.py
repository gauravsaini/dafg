"""Tests for Invariant I8: Attributable Execution Evidence and Integrity Verification."""

import hashlib
import json
import pytest
from pathlib import Path

from dafg.gates import Gate, GateEngine, GateLedger, ApprovalStore, EvidenceRecord


def test_evidence_record_round_trip():
    rec = EvidenceRecord(
        run_id="run_123",
        run_epoch=2,
        gate_id="G1",
        gate_signature="abcdef123456",
        command_digest="11223344",
        environment_digest="55667788",
        timestamp="2026-09-14T00:00:00Z",
        node_id="node_a",
        attempt_id=1,
        match_preview="ALL_PASS",
    )
    serialized = rec.serialize()
    ev_str = f"exit_code=0 timestamp=2026-09-14T00:00:00Z match='ALL_PASS' epoch=2 sig=abcdef123456 record={serialized}"

    parsed = EvidenceRecord.parse_evidence_string(ev_str)
    assert parsed is not None
    assert parsed.run_id == "run_123"
    assert parsed.run_epoch == 2
    assert parsed.gate_id == "G1"
    assert parsed.gate_signature == "abcdef123456"
    assert parsed.command_digest == "11223344"
    assert parsed.environment_digest == "55667788"
    assert parsed.node_id == "node_a"
    assert parsed.attempt_id == 1


def test_gate_execution_binds_evidence_record(tmp_path):
    gate = Gate(
        id="G1",
        title="Check Integrity",
        check="python3 -c \"print('OK_INTEGRITY')\"",
        expect="OK_INTEGRITY",
        status="PENDING",
    )
    ledger = GateLedger(work_dir=tmp_path)
    ledger.gates["G1"] = gate

    engine = GateEngine(auto_approve=True)
    res = engine.execute_gate(
        gate,
        ledger=ledger,
        context={"run_id": "run_test_42", "run_epoch": 3, "node_id": "worker_1", "attempt_id": 2},
    )

    assert res.status == "MET"
    assert res.evidence is not None

    rec = EvidenceRecord.parse_evidence_string(res.evidence)
    assert rec is not None
    assert rec.run_id == "run_test_42"
    assert rec.run_epoch == 3
    assert rec.gate_id == "G1"
    assert rec.node_id == "worker_1"
    assert rec.attempt_id == 2
    assert rec.gate_signature == ApprovalStore.signature(gate)
    assert rec.command_digest == hashlib.sha256(gate.check.encode("utf-8")).hexdigest()


def test_tampered_gate_signature_rejects_cached_evidence(tmp_path):
    gate = Gate(
        id="G1",
        title="Original Gate",
        check="python3 -c \"print('ORIGINAL')\"",
        expect="ORIGINAL",
        status="PENDING",
    )
    ledger = GateLedger(work_dir=tmp_path)
    ledger.gates["G1"] = gate

    engine = GateEngine(auto_approve=True)
    res = engine.execute_gate(gate, ledger=ledger, context={"run_epoch": 1})
    assert res.status == "MET"
    assert gate.status == "MET"

    # Now simulate tampering: modify check command without changing evidence
    gate.check = "python3 -c \"print('TAMPERED')\""
    gate.expect = "TAMPERED"

    # Signature has changed! Cached execution (reverify=False) must detect signature mismatch and demote
    res2 = engine.execute_gate(gate, ledger=ledger, reverify=False, context={"run_epoch": 1})
    # Since reverify=False failed integrity check, it fell through to run the tampered command and passed under new signature
    rec2 = EvidenceRecord.parse_evidence_string(res2.evidence)
    assert rec2.gate_signature == ApprovalStore.signature(gate)
    assert rec2.command_digest == hashlib.sha256(gate.check.encode("utf-8")).hexdigest()


def test_stale_epoch_rejects_cached_evidence(tmp_path):
    gate = Gate(
        id="G1",
        title="Check Epoch",
        check="python3 -c \"print('EPOCH_PASS')\"",
        expect="EPOCH_PASS",
        status="PENDING",
    )
    ledger = GateLedger(work_dir=tmp_path)
    ledger.gates["G1"] = gate

    engine = GateEngine(auto_approve=True)
    res1 = engine.execute_gate(gate, ledger=ledger, context={"run_epoch": 1})
    assert res1.status == "MET"

    # Next execution belongs to epoch 2 (e.g. after interruption recovery)
    # Cached check with reverify=False must reject evidence from epoch 1
    res2 = engine.execute_gate(gate, ledger=ledger, reverify=False, context={"run_epoch": 2})
    assert res2.status == "MET"
    rec2 = EvidenceRecord.parse_evidence_string(res2.evidence)
    assert rec2.run_epoch == 2
