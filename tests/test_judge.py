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
