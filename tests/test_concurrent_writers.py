"""Tests for Invariant I6: Transactional CAS and Artifact Consistency Guard."""

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import pytest

from dafg.runtime import StateStore, OptimisticConcurrencyConflictError, DAFG, TaskNode, NodeStatus, Budget
from dafg.gates import Gate, GateLedger, ApprovalStore, EvidenceRecord
from dafg.organism import ArtifactConsistencyGuard


def make_gates_md(gate_id="G1", title="Gate", check="python3 -c \"print('OK')\"", expect="OK", status="PENDING", evidence=None, abandon_reason=None):
    mark = "x" if status == "MET" else " "
    lines = [f"- [{mark}] {gate_id}: {title}"]
    if check:
        lines.append(f"  CHECK: {check}")
    if expect:
        lines.append(f"  EXPECT: {expect}")
    lines.append("  OWNS: src/core.py")
    if evidence:
        lines.append(f"  EVIDENCE: {evidence}")
    if abandon_reason:
        lines.append(f"  ABANDON: {gate_id} {abandon_reason}")
    return "\n".join(lines) + "\n"


def test_state_store_commit_increments_version(tmp_path):
    state_file = tmp_path / "state.json"
    
    # 1. Initial commit
    v1 = StateStore.commit(state_file, {"data": "initial"}, expected_version=0)
    assert v1 == 1
    loaded1 = StateStore.load(state_file)
    assert loaded1["state_version"] == 1
    assert loaded1["data"] == "initial"

    # 2. Sequential valid CAS commit
    v2 = StateStore.commit(state_file, {"data": "updated"}, expected_version=1)
    assert v2 == 2
    loaded2 = StateStore.load(state_file)
    assert loaded2["state_version"] == 2
    assert loaded2["data"] == "updated"


def test_state_store_cas_rejects_stale_version(tmp_path):
    state_file = tmp_path / "state.json"
    v1 = StateStore.commit(state_file, {"val": 1}, expected_version=0)
    assert v1 == 1

    # Another writer commits version 2
    v2 = StateStore.commit(state_file, {"val": 2}, expected_version=1)
    assert v2 == 2

    # Stale writer attempts to commit expecting version 1 -> Must raise OptimisticConcurrencyConflictError
    with pytest.raises(OptimisticConcurrencyConflictError) as exc_info:
        StateStore.commit(state_file, {"val": "stale"}, expected_version=1)
    assert "CAS version mismatch" in str(exc_info.value)


def test_concurrent_writers_with_cas_prevent_lost_updates(tmp_path):
    """Multiple concurrent writers attempting CAS commits on shared state."""
    state_file = tmp_path / "concurrent_state.json"
    StateStore.commit(state_file, {"counter": 0}, expected_version=0)

    num_writers = 10
    successes = 0
    conflicts = 0

    def worker_attempt():
        data = StateStore.load(state_file)
        cur_ver = data.get("state_version", 0)
        new_data = dict(data)
        new_data["counter"] = data.get("counter", 0) + 1
        return StateStore.commit(state_file, new_data, expected_version=cur_ver)

    with ThreadPoolExecutor(max_workers=num_writers) as executor:
        futures = [executor.submit(worker_attempt) for _ in range(num_writers)]
        for f in as_completed(futures):
            try:
                f.result()
                successes += 1
            except OptimisticConcurrencyConflictError:
                conflicts += 1

    assert successes + conflicts == num_writers
    assert successes >= 1
    final_data = StateStore.load(state_file)
    # Initial commit was version 1; each successful writer incremented it by 1
    assert final_data["state_version"] == 1 + successes


def test_artifact_consistency_guard_passes_consistent_bundle(tmp_path):
    state_file = tmp_path / "state.json"
    gates_file = tmp_path / "GATES.md"
    approvals_file = tmp_path / ".approved_gates.json"
    dummy_gate = Gate(
        id="G1",
        title="Check system health",
        check="python3 -c \"print('OK')\"",
        expect="OK",
        status="MET",
    )
    sig = ApprovalStore.signature(dummy_gate)
    cmd_digest = hashlib.sha256(dummy_gate.check.encode("utf-8")).hexdigest()
    rec = EvidenceRecord(
        run_id="local_run",
        run_epoch=1,
        gate_id="G1",
        gate_signature=sig,
        command_digest=cmd_digest,
        environment_digest="env123",
        timestamp="2026-09-14T00:00:00Z",
        match_preview="OK",
    )
    ev_str = f"exit_code=0 timestamp=2026-09-14T00:00:00Z match='OK' epoch=1 sig={sig[:12]} record={rec.serialize()}"

    # Write GATES.md
    gates_md = make_gates_md(
        gate_id="G1",
        title="Check system health",
        check="python3 -c \"print('OK')\"",
        expect="OK",
        status="MET",
        evidence=ev_str,
    )
    gates_file.write_text(gates_md, encoding="utf-8")
    ledger = GateLedger.parse(gates_md, filepath=gates_file)
    gate = ledger.gates["G1"]

    # Setup Approvals
    approvals_file.write_text(json.dumps([sig]), encoding="utf-8")

    # Setup State
    state = {
        "version": "1.0",
        "state_version": 1,
        "is_sealed": True,
        "gate_states": {
            "G1": {
                "status": "MET",
                "evidence": gate.evidence,
                "abandon_reason": None,
            }
        },
    }
    state_file.write_text(json.dumps(state), encoding="utf-8")

    ok, violations = ArtifactConsistencyGuard.verify(
        state_path=state_file,
        gates_path=gates_file,
        approvals_path=approvals_file,
    )
    assert ok is True
    assert violations == []


def test_artifact_consistency_guard_catches_unapproved_met_gate(tmp_path):
    state_file = tmp_path / "state.json"
    gates_file = tmp_path / "GATES.md"
    approvals_file = tmp_path / ".approved_gates.json"

    gates_md = make_gates_md(
        gate_id="G1",
        title="Tampered Gate",
        check="python3 -c \"print('HACKED')\"",
        expect="HACKED",
        status="MET",
        evidence="exit_code=0 timestamp=2026-09-14T00:00:00Z match='HACKED'",
    )
    gates_file.write_text(gates_md, encoding="utf-8")

    # Approvals file is empty
    approvals_file.write_text(json.dumps([]), encoding="utf-8")

    state = {
        "version": "1.0",
        "gate_states": {"G1": {"status": "MET"}},
    }
    state_file.write_text(json.dumps(state), encoding="utf-8")

    ok, violations = ArtifactConsistencyGuard.verify(
        state_path=state_file,
        gates_path=gates_file,
        approvals_path=approvals_file,
    )
    assert ok is False
    assert any("not approved in .approved_gates.json" in v for v in violations)


def test_artifact_consistency_guard_catches_state_gate_status_divergence(tmp_path):
    state_file = tmp_path / "state.json"
    gates_file = tmp_path / "GATES.md"
    approvals_file = tmp_path / ".approved_gates.json"

    gates_md = make_gates_md(
        gate_id="G1",
        title="Health Check",
        check="python3 -c \"print('OK')\"",
        expect="OK",
        status="MET",
        evidence="exit_code=0 timestamp=2026-09-14T00:00:00Z match='OK'",
    )
    gates_file.write_text(gates_md, encoding="utf-8")
    ledger = GateLedger.parse(gates_md, filepath=gates_file)
    sig = ApprovalStore.signature(ledger.gates["G1"])
    approvals_file.write_text(json.dumps([sig]), encoding="utf-8")

    # Divergent state.json says G1 is FAILED
    state = {
        "version": "1.0",
        "gate_states": {"G1": {"status": "FAILED"}},
    }
    state_file.write_text(json.dumps(state), encoding="utf-8")

    ok, violations = ArtifactConsistencyGuard.verify(
        state_path=state_file,
        gates_path=gates_file,
        approvals_path=approvals_file,
    )
    assert ok is False
    assert any("status mismatch" in v for v in violations)


def test_artifact_consistency_guard_blocks_sealed_state_with_pending_gate(tmp_path):
    state_file = tmp_path / "state.json"
    gates_file = tmp_path / "GATES.md"
    approvals_file = tmp_path / ".approved_gates.json"

    gates_md = make_gates_md(
        gate_id="G1",
        title="Pending Gate",
        check="python3 -c \"print('OK')\"",
        expect="OK",
        status="PENDING",
    )
    gates_file.write_text(gates_md, encoding="utf-8")
    approvals_file.write_text(json.dumps([]), encoding="utf-8")

    state = {
        "version": "1.0",
        "is_sealed": True,
        "gate_states": {"G1": {"status": "PENDING"}},
    }
    state_file.write_text(json.dumps(state), encoding="utf-8")

    ok, violations = ArtifactConsistencyGuard.verify(
        state_path=state_file,
        gates_path=gates_file,
        approvals_path=approvals_file,
    )
    assert ok is False
    assert any("still UNMET in GATES.md" in v for v in violations)
