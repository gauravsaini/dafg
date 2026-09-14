"""Adversarial Hardening Verification Suite.

Exercises the 7 adversarial attack vectors across:
1. Arbitrary-code CHECK escape boundary & hardlink escape detection.
2. Runtime CAS lost-update race & optimistic concurrency conflict resolution.
3. Evidence-without-record rejection (legacy evidence demotion).
4. Future-epoch evidence rejection (strict run_epoch equality).
5. Command-digest mismatch rejection.
6. Mutated test harness detection by IndependentGoalEvaluator.
7. Stale worker post-recovery attempting all commit transition paths (ACCEPT_VERDICT, FASTPATH_COMMIT).
"""

import hashlib
import json
import os
from pathlib import Path
import pytest

from dafg.sandbox import SubprocessExecutionBoundary, SubprocessSandbox, SandboxSecurityViolation
from dafg.runtime import DAFG, StateStore, OptimisticConcurrencyConflictError, TaskNode, NodeStatus, Budget
from dafg.protocol import Action, DispatchIdentity, ProtocolCommand, ProtocolState, StaleDispatchError
from dafg.gates import Gate, GateLedger, GateEngine, ApprovalStore, EvidenceRecord
from dafg.organism import (
    ArtifactConsistencyGuard,
    GoalManifest,
    IndependentGoalEvaluator,
    ModuleSpec,
    OrganismGenesis,
)


def test_adversarial_arbitrary_code_escape_boundary_and_hardlink(tmp_path):
    """Vector 1: Arbitrary-code CHECK escape boundary and hardlink validation."""
    boundary = SubprocessExecutionBoundary(workdir=tmp_path)

    # 1. Environment sanitization & isolation
    os.environ["AWS_SECRET_ACCESS_KEY"] = "super_secret_aws"
    os.environ["DAFG_API_KEY"] = "dafg_secret"
    try:
        clean_env = boundary.build_sanitized_env()
        assert "AWS_SECRET_ACCESS_KEY" not in clean_env
        assert "DAFG_API_KEY" not in clean_env
        assert clean_env["HTTP_PROXY"] == "http://127.0.0.1:0"
    finally:
        os.environ.pop("AWS_SECRET_ACCESS_KEY", None)
        os.environ.pop("DAFG_API_KEY", None)

    # 2. Arbitrary code flag (-c) runs safely contained
    res = boundary.run('python3 -c "print(\'contained_test\')"')
    assert res.returncode == 0
    assert "contained_test" in res.stdout

    # 3. Path traversal blocked
    outside_dir = tmp_path.parent / "external_forbidden"
    outside_dir.mkdir(parents=True, exist_ok=True)
    with pytest.raises(SandboxSecurityViolation):
        boundary.run("echo test", cwd=outside_dir)

    # 4. Hardlink escape detection
    external_file = outside_dir / "external_secret.txt"
    external_file.write_text("classified data", encoding="utf-8")
    hardlinked_file = tmp_path / "hardlink_to_external.txt"
    try:
        os.link(external_file, hardlinked_file)
        # Attempting to validate path of hardlink linking outside workdir must raise SandboxSecurityViolation
        with pytest.raises(SandboxSecurityViolation) as exc_info:
            boundary.validate_target_path(hardlinked_file)
        assert "Hardlink escape blocked" in str(exc_info.value)
    except OSError:
        pass

    # 5. Legitimate internal hardlink within workdir is allowed
    internal_orig = tmp_path / "internal_orig.txt"
    internal_orig.write_text("internal data", encoding="utf-8")
    internal_link = tmp_path / "internal_link.txt"
    try:
        os.link(internal_orig, internal_link)
        validated = boundary.validate_target_path(internal_link)
        assert validated == internal_link.resolve()
    except OSError:
        pass


def test_adversarial_runtime_cas_lost_update_race(tmp_path):
    """Vector 2: Runtime CAS lost-update race with conflict detection and retry."""
    state_file = tmp_path / "state.json"
    g1 = DAFG(
        nodes={"n1": TaskNode(id="n1", title="Task 1")},
        state_path=state_file,
    )
    assert g1.state_version == 1

    # Instance 2 loads current state
    g2 = DAFG.load_state(state_file)
    assert g2.state_version == 1

    # Instance 1 modifies node n1 and saves -> state_version becomes 2
    g1.nodes["n1"].attempts = 2
    g1.save_state()
    assert g1.state_version == 2

    # Instance 2 adds a new node n2 while holding stale state_version (1)
    g2.nodes["n2"] = TaskNode(id="n2", title="Task 2")
    # g2.save_state() detects CAS mismatch (expected 1 != on-disk 2), reloads, reconciles, and commits
    g2.save_state()
    assert g2.state_version == 3

    # Reload from disk: both n1 (with attempts=2) and n2 must exist (no lost updates!)
    canonical = DAFG.load_state(state_file)
    assert canonical.state_version == 3
    assert "n1" in canonical.nodes
    assert canonical.nodes["n1"].attempts == 2
    assert "n2" in canonical.nodes

    # Verify that explicit expected_version mismatch raises OptimisticConcurrencyConflictError
    with pytest.raises(OptimisticConcurrencyConflictError):
        g2.save_state(expected_version=999)


def test_adversarial_evidence_without_record_rejected(tmp_path):
    """Vector 3: Evidence-without-record rejection (legacy evidence demotion)."""
    gates_file = tmp_path / "GATES.md"
    approvals_file = tmp_path / ".approved_gates.json"
    state_file = tmp_path / "state.json"

    # Ledger has gate marked MET with legacy string lacking record={...}
    text = """- [x] G1: Legacy Gate
  CHECK: python3 -c "print('OK')"
  EXPECT: OK
  OWNS: src/core.py
  EVIDENCE: exit_code=0 timestamp=2026-09-14T00:00:00Z match='OK'
"""
    gates_file.write_text(text, encoding="utf-8")
    ledger = GateLedger.load(gates_file)
    gate = ledger.gates["G1"]
    sig = ApprovalStore.signature(gate)
    approvals_file.write_text(json.dumps([sig]), encoding="utf-8")

    # 1. GateEngine execute_gate with reverify=False must reject evidence without record
    engine = GateEngine(auto_approve=True, allow_regression=True)
    res = engine.execute_gate(gate, ledger=ledger, reverify=False, context={"run_epoch": 1})
    assert res.status == "MET"
    # The evidence has now been upgraded with an EvidenceRecord token
    rec = EvidenceRecord.parse_evidence_string(res.evidence)
    assert rec is not None
    assert rec.command_digest == hashlib.sha256(gate.check.encode("utf-8")).hexdigest()

    # 2. ArtifactConsistencyGuard must flag a MET gate that lacks an EvidenceRecord
    gates_file.write_text(text, encoding="utf-8")  # Reset to legacy text
    state = {
        "version": "1.0",
        "gate_states": {"G1": {"status": "MET", "evidence": "exit_code=0 match='OK'"}},
    }
    state_file.write_text(json.dumps(state), encoding="utf-8")
    ok, violations = ArtifactConsistencyGuard.verify(state_file, gates_file, approvals_file)
    assert ok is False
    assert any("missing a valid EvidenceRecord" in v for v in violations)


def test_adversarial_future_epoch_evidence_rejected(tmp_path):
    """Vector 4: Future-epoch evidence rejection (strict run_epoch equality)."""
    gate = Gate(
        id="G1",
        title="Check Epoch",
        check="python3 -c \"print('OK_EPOCH')\"",
        expect="OK_EPOCH",
        status="MET",
    )
    sig = ApprovalStore.signature(gate)
    cmd_digest = hashlib.sha256(gate.check.encode("utf-8")).hexdigest()

    # Evidence forged with a future epoch (e.g. 99)
    future_rec = EvidenceRecord(
        run_id="run_1",
        run_epoch=99,
        gate_id="G1",
        gate_signature=sig,
        command_digest=cmd_digest,
        environment_digest="env1",
        timestamp="2026-09-14T00:00:00Z",
        match_preview="OK_EPOCH",
    )
    gate.evidence = f"exit_code=0 timestamp=now match='OK_EPOCH' epoch=99 sig={sig[:12]} record={future_rec.serialize()}"

    ledger = GateLedger(work_dir=tmp_path)
    ledger.gates["G1"] = gate

    engine = GateEngine(auto_approve=True, allow_regression=True)
    # Running under context epoch=1 must reject cached evidence from future epoch=99
    res = engine.execute_gate(gate, ledger=ledger, reverify=False, context={"run_epoch": 1, "run_id": "run_1"})
    assert res.status == "MET"
    # Re-execution occurred and record epoch was reset to current epoch (1)
    new_rec = EvidenceRecord.parse_evidence_string(res.evidence)
    assert new_rec is not None
    assert new_rec.run_epoch == 1


def test_adversarial_command_digest_mismatch_rejected(tmp_path):
    """Vector 5: Command-digest mismatch rejection."""
    gate = Gate(
        id="G1",
        title="Command Digest Gate",
        check="python3 -c \"print('CHECK_A')\"",
        expect="CHECK_A",
        status="MET",
    )
    sig = ApprovalStore.signature(gate)
    # Record generated for CHECK_B
    stale_digest = hashlib.sha256(b"python3 -c \"print('CHECK_B')\"").hexdigest()
    mismatched_rec = EvidenceRecord(
        run_id="run_1",
        run_epoch=1,
        gate_id="G1",
        gate_signature=sig,
        command_digest=stale_digest,
        environment_digest="env1",
        timestamp="2026-09-14T00:00:00Z",
        match_preview="CHECK_A",
    )
    gate.evidence = f"exit_code=0 match='CHECK_A' record={mismatched_rec.serialize()}"

    ledger = GateLedger(work_dir=tmp_path)
    ledger.gates["G1"] = gate

    engine = GateEngine(auto_approve=True)
    # reverify=False must detect the digest mismatch and reject the cached evidence
    res = engine.execute_gate(gate, ledger=ledger, reverify=False, context={"run_epoch": 1, "run_id": "run_1"})
    assert res.status == "MET"
    rec = EvidenceRecord.parse_evidence_string(res.evidence)
    assert rec.command_digest == hashlib.sha256(gate.check.encode("utf-8")).hexdigest()


def test_adversarial_mutated_test_harness_rejected_by_evaluator(tmp_path):
    """Vector 6: Mutated test_system.py detection by IndependentGoalEvaluator."""
    manifest = GoalManifest(
        goal="Build robust key-value store",
        system_name="kv_store",
        language="python",
        entry_point="src/core.py",
        modules=[
            ModuleSpec(
                name="core",
                file_path="src/core.py",
                owns=["src/core.py"],
                responsibilities=[],
                suggested_role="coder",
                gate_id="G1",
                gate_title="Core Gate",
                check_command="python3 -c 'print(\"CORE_PASS\")'",
                expect_pattern="CORE_PASS",
            ),
            ModuleSpec(
                name="storage",
                file_path="src/storage.py",
                owns=["src/storage.py"],
                responsibilities=[],
                suggested_role="coder",
                gate_id="G2",
                gate_title="Storage Gate",
                check_command="python3 -c 'print(\"STORAGE_PASS\")'",
                expect_pattern="STORAGE_PASS",
            ),
            ModuleSpec(
                name="protocol",
                file_path="src/protocol.py",
                owns=["src/protocol.py"],
                responsibilities=[],
                suggested_role="coder",
                gate_id="G3",
                gate_title="Protocol Gate",
                check_command="python3 -c 'print(\"PROTOCOL_PASS\")'",
                expect_pattern="PROTOCOL_PASS",
            ),
            ModuleSpec(
                name="metrics",
                file_path="src/metrics.py",
                owns=["src/metrics.py"],
                responsibilities=[],
                suggested_role="coder",
                gate_id="G4",
                gate_title="Metrics Gate",
                check_command="python3 -c 'print(\"METRICS_PASS\")'",
                expect_pattern="METRICS_PASS",
            ),
            ModuleSpec(
                name="security",
                file_path="src/security.py",
                owns=["src/security.py"],
                responsibilities=[],
                suggested_role="coder",
                gate_id="G5",
                gate_title="Security Gate",
                check_command="python3 -c 'print(\"SECURITY_PASS\")'",
                expect_pattern="SECURITY_PASS",
            ),
        ],
        integration_gate_id="G_E2E",
        integration_gate_title="E2E Integration",
        integration_check="python3 test_system.py E2E",
        integration_expect="E2E_PASS",
        all_owns=["src/core.py", "src/storage.py", "src/protocol.py", "src/metrics.py", "src/security.py"],
    )

    # Scaffold pristine test harness
    test_file = OrganismGenesis.scaffold_test_runner(manifest, tmp_path)
    assert test_file.exists()
    assert manifest.test_harness_digest != ""
    pristine_digest = manifest.test_harness_digest

    # Pristine test harness passes evaluation (with stub init_core)
    ok, msg = IndependentGoalEvaluator.evaluate_system(manifest, tmp_path)
    assert ok is True
    assert "Independent goal verification succeeded" in msg

    # Adversary tampers with test_system.py on disk (e.g. injects fake bypass)
    test_file.write_text('print("E2E_PASS")\n', encoding="utf-8")

    # Evaluator must catch the tampering and reject immediately
    tampered_ok, tampered_msg = IndependentGoalEvaluator.evaluate_system(manifest, tmp_path)
    assert tampered_ok is False
    assert "Test harness tampered" in tampered_msg
    assert pristine_digest in tampered_msg


def test_adversarial_stale_worker_post_recovery_all_commit_paths_blocked(tmp_path):
    """Vector 7: Stale worker post-recovery attempting commit transition paths raises StaleDispatchError."""
    state_file = tmp_path / "state.json"
    node = TaskNode(
        id="n1",
        title="Compute node",
        status=NodeStatus.RUNNING,
    )
    node.protocol_state = ProtocolState.VERIFYING
    node.epoch = 1
    node.active_dispatch = DispatchIdentity(
        run_id="run_1",
        node_id="n1",
        epoch=1,
        attempt_id=1,
        context_snapshot_id="snap_1",
        contract_version=1,
    )

    graph = DAFG(
        nodes={"n1": node},
        state_path=state_file,
    )
    graph.run_id = "run_1"
    graph.run_epoch = 1
    # Save state with node in RUNNING
    graph.save_state()

    # Simulate crash and resume: load_state detects interrupted node, resets to PENDING, clears active_dispatch, bumps epoch to 2
    resumed = DAFG.load_state(state_file)
    assert resumed.run_epoch == 2
    assert resumed.nodes["n1"].epoch == 2
    assert resumed.nodes["n1"].active_dispatch is None
    assert resumed.nodes["n1"].status == NodeStatus.PENDING

    stale_identity = DispatchIdentity(
        run_id="run_1",
        node_id="n1",
        epoch=1,
        attempt_id=1,
        context_snapshot_id="snap_1",
        contract_version=1,
    )

    # 1. Attempt commit via ACCEPT_VERDICT from stale worker
    cmd_accept = ProtocolCommand(
        idempotency_key="delayed_accept_worker_1",
        action=Action.ACCEPT_VERDICT,
        node_id="n1",
        run_id="run_1",
        dispatch_identity=stale_identity,
        payload={"result": {"val": 42}},
    )
    with pytest.raises(StaleDispatchError) as exc_info1:
        resumed.submit_command(cmd_accept)
    assert "Stale dispatch identity" in str(exc_info1.value)

    # 2. Attempt commit via FASTPATH_COMMIT from stale worker
    cmd_fastpath = ProtocolCommand(
        idempotency_key="delayed_fastpath_worker_1",
        action=Action.FASTPATH_COMMIT,
        node_id="n1",
        run_id="run_1",
        dispatch_identity=stale_identity,
        payload={"result": {"val": 42}},
    )
    with pytest.raises(StaleDispatchError) as exc_info2:
        resumed.submit_command(cmd_fastpath)
    assert "Stale dispatch identity" in str(exc_info2.value)


def test_adversarial_end_to_end_malicious_gates_blocked_under_auto_approve(tmp_path):
    """Vector 8: Live end-to-end wiring check — malicious GATES.md intercepted by GateEngine under auto_approve."""
    # Scaffold simple script
    script = tmp_path / "test_system.js"
    script.write_text("console.log('OK', process.argv[2] || '');\n", encoding="utf-8")

    # Author ledger with legitimate and malicious gates
    gates_content = """# Gates
- [ ] G1: Legitimate check
  CHECK: node test_system.js CORE
  EXPECT: OK CORE
  OWNS: test_system.js
- [ ] G2: Malicious traversal check
  CHECK: node test_system.js ../../../etc/passwd
  EXPECT: root
  OWNS: test_system.js
- [ ] G3: Malicious inline code check
  CHECK: node -e "require('child_process').execSync('id')"
  EXPECT: uid
  OWNS: test_system.js
"""
    gates_path = tmp_path / "GATES.md"
    gates_path.write_text(gates_content, encoding="utf-8")

    from dafg.gates import GateLedger, GateEngine
    ledger = GateLedger.load(gates_path)
    state_file = tmp_path / "state.json"
    engine = GateEngine(auto_approve=True, enforce_safe_policy=True)
    graph = DAFG(ledger=ledger, engine=engine, state_path=state_file)
    graph.init_from_ledger()

    # Execute graph run under auto_approve
    status = graph.run()
    assert status == "FAILED"

    # G1 was met with recorded evidence
    assert ledger.gates["G1"].status == "MET"
    assert ledger.gates["G1"].evidence is not None

    # G2 was intercepted and failed with security policy violation
    assert ledger.gates["G2"].status != "MET"
    res_g2 = engine.execute_gate(ledger.gates["G2"])
    assert res_g2.status == "FAILED"
    assert "Security violation" in res_g2.error
    assert "must match ^[a-zA-Z0-9_-]+$" in res_g2.error

    # G3 was intercepted and failed with code execution pattern violation
    assert ledger.gates["G3"].status != "MET"
    res_g3 = engine.execute_gate(ledger.gates["G3"])
    assert res_g3.status == "FAILED"
    assert "Security violation" in res_g3.error
    assert "child_process" in res_g3.error

