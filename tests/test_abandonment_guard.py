"""Tests for Structured Abandonment, Stop Hook Handoff, and Epistemic Quality Verdicts."""

import pytest
from dafg.gates import GateLedger
from dafg.hook import CompletionGuard
from dafg.judge import QualityVerdict, RunJudge
from dafg.runtime import DAFG, OutcomeStatus, TaskNode, NodeStatus


def test_stop_hook_rejects_trivial_or_vacuous_abandonment_reasons():
    text_trivial_1 = """
- [-] G1: Trivial token
  ABANDON: done
"""
    ledger = GateLedger.parse(text_trivial_1)
    guard = CompletionGuard(ledger=ledger)
    decision = guard.evaluate()
    assert not decision.allowed
    assert "abandoned without reason" in decision.reason or "insufficient" in decision.reason

    text_trivial_2 = """
- [-] G2: Short phrase
  ABANDON: will skip
"""
    ledger2 = GateLedger.parse(text_trivial_2)
    guard2 = CompletionGuard(ledger=ledger2)
    decision2 = guard2.evaluate()
    assert not decision2.allowed


def test_stop_hook_allows_structured_abandonment_yielding_handoff_required():
    text = """
- [x] G1: Successful gate
  CHECK: python -c "print('ok')"
  EXPECT: ok
  EVIDENCE: exit_code=0 timestamp=2026-09-14T00:00:00Z match='ok'

- [-] G2: Hardware telemetry gate
  ABANDON: reason="Missing physical CAN bus hardware" attempted_actions="Emulated packet loopback" blocker="Kernel transceiver missing" residual_risk="Hardware telemetry unverified"
"""
    ledger = GateLedger.parse(text)
    guard = CompletionGuard(ledger=ledger)
    decision = guard.evaluate()

    assert decision.allowed
    assert decision.decision == "allow"
    assert "G2" in decision.abandoned_gates
    assert decision.outcome_status == "HANDOFF_REQUIRED"


def test_judge_evaluates_handoff_required_as_distinct_epistemic_verdict(tmp_path):
    # Setup graph where ledger completed with an abandoned gate
    text = """
- [x] G1: Met gate
  CHECK: python -c "print('ok')"
  EXPECT: ok
  EVIDENCE: exit_code=0 timestamp=2026-09-14T00:00:00Z match='ok'

- [-] G2: Abandoned gate
  ABANDON: reason="Physical device unavailable in test environment" attempted_actions="Tested mock interfaces" blocker="Hardware driver absent" residual_risk="Device integration pending hardware bench"
"""
    ledger_file = tmp_path / "GATES.md"
    ledger_file.write_text(text, encoding="utf-8")
    ledger = GateLedger.load(ledger_file)

    graph = DAFG(ledger=ledger, state_path=tmp_path / "state.json")
    n1 = TaskNode("n1", "Work 1", assigned_gates=["G1"])
    graph.add_node(n1)
    graph.nodes["n1"].status = NodeStatus.ACCEPTED

    # Resolve run with abandoned gate
    graph.seal_run()
    graph.outcome_status = OutcomeStatus.HANDOFF_REQUIRED
    graph.save_state()

    report = RunJudge.evaluate(graph)
    assert report.outcome_status == "HANDOFF_REQUIRED"
    assert report.verdict == QualityVerdict.HANDOFF_REQUIRED
    assert report.score <= 75.0  # Capped below PERFECT threshold
