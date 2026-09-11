"""Tests for DAFG v0.2 Layered Verification & Evidence Types."""

import pytest
from pathlib import Path
import tempfile

from dafg import (
    DAFG,
    AgentResponse,
    ApprovalStore,
    CriterionEvidence,
    EvidenceType,
    GateEngine,
    GateLedger,
    InputManifestSchema,
    InterfaceContract,
    InterfaceContractSchema,
    NodeStatus,
    OutcomeStatus,
    RevisionDirectiveSchema,
    TaskNode,
)
from dafg.hook import CompletionGuard


def test_criterion_evidence_typed_records():
    """Verify nodes accumulate typed CriterionEvidence records."""
    graph = DAFG()

    contract = InterfaceContract(
        contract_id="user_service",
        version=1,
        owner="t1",
        invariants=["user.id > 0"],
    )
    graph.register_contract(contract)

    node = TaskNode(id="t1", title="User Service Implementation")
    graph.add_node(node)

    def executor(n, ctx):
        ev = CriterionEvidence(
            criterion_id="spec_review",
            status="MET",
            evidence_type=EvidenceType.MODEL_JUDGMENT,
            evidence_ref="Peer review confirmed schema conformance",
        )
        return AgentResponse(
            output="Done",
            status="COMPLETED",
            criterion_evidence=[ev],
        )

    success = graph.execute_node(node, executor_fn=executor)
    assert success is True
    assert node.status == NodeStatus.ACCEPTED

    # Verify both the model review and contract invariant evidence were logged
    evidence_types = [e.evidence_type for e in node.evidence_ledger]
    assert EvidenceType.MODEL_JUDGMENT in evidence_types
    assert EvidenceType.INVARIANT_CHECK in evidence_types


def test_intermediate_false_acceptance_tracking():
    """Verify descendant reverification defect increments intermediate_false_acceptances."""
    with tempfile.TemporaryDirectory() as tmpdir:
        ledger_path = Path(tmpdir) / "GATES.md"
        ledger_text = """# Test Ledger
- [ ] G1: Root check
  CHECK: python -c "print('OK')"
  EXPECT: OK

- [ ] G2: Child check
  CHECK: python -c "import sys; sys.exit(0)"
  EXPECT: ""
"""
        ledger_path.write_text(ledger_text)
        ledger = GateLedger.load(ledger_path)
        appr = ApprovalStore(filepath=Path(tmpdir) / "appr.json", auto_approve=True)
        engine = GateEngine(approval_store=appr, auto_approve=True)

        graph = DAFG(ledger=ledger, engine=engine)

        parent = TaskNode(id="parent", title="Parent Task", assigned_gates=["G1"], children=["child"])
        child = TaskNode(id="child", title="Child Task", assigned_gates=["G2"], status=NodeStatus.ACCEPTED)

        graph.add_node(parent)
        graph.add_node(child)

        # Mutate child gate in ledger to make reverification fail
        ledger.get_gate("G2").check = "python -c 'import sys; sys.exit(1)'"

        res = graph.execute_node(parent)
        assert res is False
        assert graph.intermediate_false_acceptances == 1
        assert child.status == NodeStatus.REJECTED


def test_stop_hook_outcome_status_reporting():
    """Verify CompletionGuard evaluates outcome_status correctly."""
    with tempfile.TemporaryDirectory() as tmpdir:
        ledger_path = Path(tmpdir) / "GATES.md"
        ledger_path.write_text("""# Gates
- [x] G1: Valid Gate
  CHECK: python -c "print('PASS')"
  EXPECT: PASS
  EVIDENCE: exit_code=0 timestamp=2026-09-11T00:00:00Z match='PASS'
""")
        appr = ApprovalStore(auto_approve=True)
        guard = CompletionGuard(ledger_path=ledger_path, approval_store=appr)
        decision = guard.evaluate()

        assert decision.allowed is True
        assert decision.outcome_status == "VERIFIED_DELIVERY"


def test_v02_schemas_validation():
    """Verify InputManifestSchema and RevisionDirectiveSchema validate properly."""
    manifest_data = {
        "required_inputs": [{"artifact": "auth", "version": 1}],
        "mandatory_context": ["doc1.md"],
    }
    validated_manifest = InputManifestSchema().validate(manifest_data)
    assert validated_manifest["required_inputs"][0]["artifact"] == "auth"

    directive_data = {
        "verdict": "REVISE",
        "failure_class": "STALE_DEPENDENCY",
        "affected_dependency": "auth",
        "required_version": 2,
    }
    validated_directive = RevisionDirectiveSchema().validate(directive_data)
    assert validated_directive["failure_class"] == "STALE_DEPENDENCY"
