"""Tests for DAFG Analytics Judge & Run Quality Evaluator."""

import json
from pathlib import Path

import pytest

from dafg.judge import (
    FrictionPoint,
    FrictionSeverity,
    QualityDimension,
    QualityVerdict,
    RunJudge,
    RunQualityReport,
)
from dafg.runtime import DAFG, AgentResponse, Budget, NodeStatus, TaskNode
from dafg.trends import GateRunRecord, RunSummary, TrendStore


def test_judge_perfect_run(tmp_path):
    # A clean single-shot delivery should receive PERFECT (>= 85.0)
    n1 = TaskNode(id="t1", title="Task 1", owns=["a.py"])
    graph = DAFG(nodes={"t1": n1}, state_path=tmp_path / "state.json")

    def mock_exec(node, ctx):
        return AgentResponse(output="Flawless")

    graph.step(executor_fn=mock_exec)
    graph.seal_run()

    report = RunJudge.evaluate(graph)

    assert report.verdict == QualityVerdict.PERFECT
    assert report.score >= 85.0
    assert report.outcome_status == "VERIFIED_DELIVERY"
    assert report.friction_severity_index == 0.0
    assert len(report.friction_points) == 0


def test_judge_imperfect_run_due_to_revisions(tmp_path):
    # A run with high revisions should be degraded to IMPERFECT
    n1 = TaskNode(id="t1", title="Task 1", owns=["a.py"], revisions=2)
    graph = DAFG(nodes={"t1": n1}, state_path=tmp_path / "state.json")
    n1.status = NodeStatus.ACCEPTED
    graph.seal_run()

    report = RunJudge.evaluate(graph)

    assert report.verdict == QualityVerdict.IMPERFECT
    assert report.score < 85.0
    assert any(fp.category == "REVISION_THRASH" for fp in report.friction_points)
    assert any("InterfaceContract" in rec for rec in report.recommendations)


def test_judge_failed_run(tmp_path):
    # Incomplete or failing run gets FAILED verdict
    n1 = TaskNode(id="t1", title="Task 1", owns=["a.py"], status=NodeStatus.FAILED)
    graph = DAFG(nodes={"t1": n1}, state_path=tmp_path / "state.json")

    report = RunJudge.evaluate(graph)

    assert report.verdict == QualityVerdict.FAILED
    assert report.score < 50.0


def test_judge_owns_conflict_friction_and_recommendation(tmp_path):
    # Two nodes with overlapping OWNS paths creating serialization conflicts
    n1 = TaskNode(id="n1", title="Node 1", owns=["shared.py"])
    n2 = TaskNode(id="n2", title="Node 2", owns=["shared.py"])
    graph = DAFG(nodes={"n1": n1, "n2": n2}, state_path=tmp_path / "state.json")

    def mock_exec(node, ctx):
        return AgentResponse(output="OK")

    graph.step(executor_fn=mock_exec)
    graph.step(executor_fn=mock_exec)
    graph.seal_run()

    report = RunJudge.evaluate(graph)

    serial_fps = [fp for fp in report.friction_points if fp.category == "SERIAL_CONFLICT"]
    assert len(serial_fps) > 0
    assert serial_fps[0].severity in (FrictionSeverity.MEDIUM, FrictionSeverity.HIGH)
    assert serial_fps[0].impact > 0.0
    assert any("shared.py" in rec for rec in report.recommendations)


def test_judge_persona_effectiveness_and_thrashing(tmp_path):
    n1 = TaskNode(id="p_node", title="Persona Node", owns=["p.py"])
    # Simulate 2 persona switches on the node
    n1.metadata["persona_history"] = [
        {"from": "coder", "to": "specialist"},
        {"from": "specialist", "to": "reviewer"},
    ]
    graph = DAFG(nodes={"p_node": n1}, state_path=tmp_path / "state.json")
    n1.status = NodeStatus.ACCEPTED
    graph.seal_run()

    report = RunJudge.evaluate(graph)

    persona_dim = report.dimensions["persona_effectiveness"]
    assert persona_dim.score < 100.0
    persona_fps = [fp for fp in report.friction_points if fp.category == "PERSONA_THRASH"]
    assert len(persona_fps) == 1
    assert persona_fps[0].node_id == "p_node"
    assert any("p_node" in rec for rec in report.recommendations)


def test_judge_repair_stability_score(tmp_path):
    n1 = TaskNode(id="r_node", title="Repair Node", owns=["r.py"])
    # Simulate 2 repair attempts
    n1.metadata["repair_results"] = [
        {"gate_id": "G1", "attempts": 2, "final_status": "REPAIRED"}
    ]
    graph = DAFG(nodes={"r_node": n1}, state_path=tmp_path / "state.json")
    n1.status = NodeStatus.ACCEPTED
    graph.seal_run()

    report = RunJudge.evaluate(graph)

    repair_dim = report.dimensions["repair_stability"]
    assert repair_dim.score < 100.0
    repair_fps = [fp for fp in report.friction_points if fp.category == "REPAIR_THRASH"]
    assert len(repair_fps) == 1
    assert repair_fps[0].node_id == "r_node"
    assert any("repair diagnoser strictness" in rec.lower() for rec in report.recommendations)


def test_judge_gate_flakiness_from_trend_store(tmp_path):
    # Set up a trend store with a flaky gate
    trend_file = tmp_path / "trends.jsonl"
    store = TrendStore(filepath=trend_file)

    # Run 1: G_FLAKY passes
    store.append_run(RunSummary(
        run_id="r1",
        timestamp="2026-01-01T00:00:00",
        gate_results={"G_FLAKY": GateRunRecord(gate_id="G_FLAKY", status="MET")},
    ))
    # Run 2: G_FLAKY fails
    store.append_run(RunSummary(
        run_id="r2",
        timestamp="2026-01-01T00:01:00",
        gate_results={"G_FLAKY": GateRunRecord(gate_id="G_FLAKY", status="FAILED")},
    ))

    # Graph with G_FLAKY in gate states
    graph = DAFG()
    graph.gate_states = {"G_FLAKY": {"status": "MET"}}
    node = TaskNode(id="t1", title="Task 1", owns=["a.py"], status=NodeStatus.ACCEPTED)
    graph.add_node(node)
    graph.seal_run()

    # Mock ledger in graph to match current gates
    from dafg.gates import GateLedger
    ledger = GateLedger.parse("- [x] G_FLAKY: title\n  CHECK: echo 1\n  EXPECT: 1")
    graph.ledger = ledger

    report = RunJudge.evaluate(graph, trend_store_path=trend_file)

    assert report.gate_flakiness_index > 0.0
    flaky_fps = [fp for fp in report.friction_points if fp.category == "GATE_FLAKINESS"]
    assert len(flaky_fps) == 1
    assert flaky_fps[0].gate_id == "G_FLAKY"
    assert any("Stabilize flaky gate 'G_FLAKY'" in rec for rec in report.recommendations)


def test_judge_report_formatting():
    dim1 = QualityDimension(name="Convergence Discipline", score=90.0, weight=0.25, summary="clean")
    dim2 = QualityDimension(name="Verification Integrity", score=85.0, weight=0.25, summary="all met")
    dim3 = QualityDimension(name="Concurrency Health", score=80.0, weight=0.15, summary="good")
    dim4 = QualityDimension(name="Resource Economy", score=95.0, weight=0.15, summary="low burn")
    dim5 = QualityDimension(name="Persona Effectiveness", score=100.0, weight=0.10, summary="no drift")
    dim6 = QualityDimension(name="Repair Stability", score=100.0, weight=0.10, summary="no repairs")

    fp = FrictionPoint(
        category="SERIAL_CONFLICT",
        message="OWNS conflict on 'x.py'",
        severity=FrictionSeverity.MEDIUM,
        impact=0.45,
        node_id="n1",
    )

    report = RunQualityReport(
        run_id="run_test",
        verdict=QualityVerdict.PERFECT,
        score=89.5,
        outcome_status="VERIFIED_DELIVERY",
        dimensions={
            "convergence_discipline": dim1,
            "verification_integrity": dim2,
            "concurrency_health": dim3,
            "resource_economy": dim4,
            "persona_effectiveness": dim5,
            "repair_stability": dim6,
        },
        friction_points=[fp],
        recommendations=["Split 'x.py' ownership."],
        friction_severity_index=0.45,
        gate_flakiness_index=0.0,
    )

    formatted = report.format_report()
    assert "DAFG RUN QUALITY REPORT" in formatted
    assert "PERFECT (Score: 89.5/100)" in formatted
    assert "FRICTION SEVERITY INDEX: 0.45" in formatted
    assert "GATE FLAKINESS INDEX:    0.00" in formatted
    assert "[SERIAL_CONFLICT]" in formatted
    assert "Split 'x.py' ownership." in formatted


def test_judge_docks_points_and_logs_friction_on_low_coverage():
    """RunJudge docks Verification Integrity points and logs LOW_EVIDENCE_COVERAGE when coverage < 50%."""
    # Test 1: Coverage = 25.0% (severity MEDIUM)
    analytics_med = {
        "run_id": "test_med_cov",
        "funnel": {"accepted_nodes": 1, "total_nodes": 1},
        "concurrency": {"steps": 1, "avg_concurrency_ratio": 1.0, "total_conflict_deferrals": 0, "domain_deferrals": 0},
        "triad": {},
        "critical_path": {},
        "budget": {},
        "gates": {
            "available": True,
            "total": 4,
            "met": 4,
            "pending": 0,
            "abandoned": 0,
            "pass_rate": 1.0,
            "evidence_coverage": 25.0,
            "coverage_pct": 25.0,
        },
    }
    report_med = RunJudge.evaluate_from_analytics(analytics_med)
    dim_verif = report_med.dimensions["verification_integrity"]
    # dock = (50 - 25) * 0.5 = 12.5 -> score = 100 - 12.5 = 87.5
    assert dim_verif.score == 87.5

    cov_fps = [fp for fp in report_med.friction_points if fp.category == "LOW_EVIDENCE_COVERAGE"]
    assert len(cov_fps) == 1
    assert cov_fps[0].severity == FrictionSeverity.MEDIUM
    assert cov_fps[0].impact == 0.5
    assert cov_fps[0].details["coverage_pct"] == 25.0
    assert any("Replace subjective manual gates with executable CHECK" in rec for rec in report_med.recommendations)

    # Test 2: Coverage = 10.0% (severity HIGH)
    analytics_high = {
        "run_id": "test_high_cov",
        "funnel": {"accepted_nodes": 1, "total_nodes": 1},
        "concurrency": {"steps": 1, "avg_concurrency_ratio": 1.0, "total_conflict_deferrals": 0, "domain_deferrals": 0},
        "triad": {},
        "critical_path": {},
        "budget": {},
        "gates": {
            "available": True,
            "total": 10,
            "met": 10,
            "pending": 0,
            "abandoned": 0,
            "pass_rate": 1.0,
            "evidence_coverage": 10.0,
            "coverage_pct": 10.0,
        },
    }
    report_high = RunJudge.evaluate_from_analytics(analytics_high)
    cov_fps_high = [fp for fp in report_high.friction_points if fp.category == "LOW_EVIDENCE_COVERAGE"]
    assert len(cov_fps_high) == 1
    assert cov_fps_high[0].severity == FrictionSeverity.HIGH
    # dock = (50 - 10) * 0.5 = 20.0 -> score = 100 - 20 = 80.0
    assert report_high.dimensions["verification_integrity"].score == 80.0


def test_judge_clean_scoring_on_adequate_coverage():
    """RunJudge does not dock points or flag friction when evidence coverage >= 50%."""
    analytics = {
        "run_id": "test_good_cov",
        "funnel": {"accepted_nodes": 1, "total_nodes": 1},
        "concurrency": {"steps": 1, "avg_concurrency_ratio": 1.0, "total_conflict_deferrals": 0, "domain_deferrals": 0},
        "triad": {},
        "critical_path": {},
        "budget": {},
        "gates": {
            "available": True,
            "total": 4,
            "met": 4,
            "pending": 0,
            "abandoned": 0,
            "pass_rate": 1.0,
            "evidence_coverage": 75.0,
            "coverage_pct": 75.0,
        },
    }
    report = RunJudge.evaluate_from_analytics(analytics)
    assert report.dimensions["verification_integrity"].score == 100.0
    cov_fps = [fp for fp in report.friction_points if fp.category == "LOW_EVIDENCE_COVERAGE"]
    assert len(cov_fps) == 0


def test_judge_derives_coverage_from_graph_ledger(tmp_path):
    """RunJudge computes coverage from raw_graph.ledger when not in analytics dictionary."""
    from dafg.gates import GateLedger
    ledger_text = """
- [x] G1: Executable check
  CHECK: echo 1
  EXPECT: 1
  EVIDENCE: exit_code=0 timestamp=2026-09-10T00:00:00Z match='1'

- [x] G2: Manual gate 1
  EVIDENCE: exit_code=0 timestamp=2026-09-10T00:00:00Z match='verified'

- [x] G3: Manual gate 2
  EVIDENCE: exit_code=0 timestamp=2026-09-10T00:00:00Z match='verified'

- [x] G4: Manual gate 3
  EVIDENCE: exit_code=0 timestamp=2026-09-10T00:00:00Z match='verified'
"""
    ledger = GateLedger.parse(ledger_text)
    node = TaskNode(id="t1", title="Task", owns=["a.py"], status=NodeStatus.ACCEPTED)
    graph = DAFG(nodes={"t1": node}, state_path=tmp_path / "state.json")
    graph.ledger = ledger
    graph.seal_run()

    report = RunJudge.evaluate(graph)
    # 1 of 4 is runnable proof = 25.0% < 50.0%
    cov_fps = [fp for fp in report.friction_points if fp.category == "LOW_EVIDENCE_COVERAGE"]
    assert len(cov_fps) == 1
    assert cov_fps[0].details["coverage_pct"] == 25.0


def test_runtime_get_run_analytics_includes_evidence_coverage(tmp_path):
    """DAFG.get_run_analytics() populates evidence_coverage and coverage_pct."""
    from dafg.gates import GateLedger
    ledger_text = """
- [x] G1: Runnable
  CHECK: echo 1
  EXPECT: 1
  EVIDENCE: exit_code=0 timestamp=2026-09-10T00:00:00Z match='1'

- [x] G2: Another runnable
  CHECK: echo 2
  EXPECT: 2
  EVIDENCE: exit_code=0 timestamp=2026-09-10T00:00:00Z match='2'

- [x] G3: Manual
  EVIDENCE: exit_code=0 timestamp=2026-09-10T00:00:00Z match='manual'
"""
    ledger = GateLedger.parse(ledger_text)
    graph = DAFG(state_path=tmp_path / "state.json")
    graph.ledger = ledger
    analytics = graph.get_run_analytics()

    assert analytics["gates"]["available"] is True
    assert analytics["gates"]["total"] == 3
    # 2 of 3 runnable proof -> 66.7%
    assert analytics["gates"]["evidence_coverage"] == 66.7
    assert analytics["gates"]["coverage_pct"] == 66.7

