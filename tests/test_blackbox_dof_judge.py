"""Independent Black-Box Execution Tests for DOF and Analytics Judge.

Treats DAFG as a sealed library and CLI application. Only public APIs,
CLI entry points, and filesystem traces are validated.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from dafg import (
    DAFG,
    AgentResponse,
    ApprovalStore,
    Gate,
    GateEngine,
    GateLedger,
    InMemoryProbe,
    JsonlProbe,
    NodeStatus,
    QualityVerdict,
    RunJudge,
    TaskNode,
)


class TestBlackBoxScenario1Flawless:
    """Scenario 1: Disjoint tasks, clean first-attempt gates, zero revisions.

    Must achieve PERFECT verdict (score >= 85.0) and generate complete DOF traces.
    """

    def test_flawless_pipeline(self, tmp_path):
        trace_file = tmp_path / "traces.jsonl"
        jsonl_probe = JsonlProbe(filepath=trace_file)
        mem_probe = InMemoryProbe()

        # Two parallel tasks with non-conflicting OWNS paths
        node_ui = TaskNode(id="build_ui", title="Build UI", owns=["frontend/app.tsx"])
        node_api = TaskNode(id="build_api", title="Build API", owns=["backend/api.py"])

        gates_text = """
- [ ] G_BB_UI: Fast UI check
  CHECK: python3 -c "print('UI_PASS')"
  EXPECT: UI_PASS
- [ ] G_BB_API: Fast API check
  CHECK: python3 -c "print('API_PASS')"
  EXPECT: API_PASS
"""
        gates_path = tmp_path / "GATES.md"
        gates_path.write_text(gates_text, encoding="utf-8")
        ledger = GateLedger.load(gates_path)

        graph = DAFG(
            nodes={"build_ui": node_ui, "build_api": node_api},
            ledger=ledger,
            state_path=tmp_path / "state.json",
            probes=[jsonl_probe, mem_probe],
        )

        def mock_worker(node, ctx):
            return AgentResponse(output="Delivered")

        # Step 1: Dispatches wave-0 with both ready nodes
        executed = graph.step(executor_fn=mock_worker)
        assert len(executed) == 2

        # Run gates
        engine = GateEngine(auto_approve=True, fabric=graph._fabric)
        res1 = engine.execute_gate(ledger.gates["G_BB_UI"], ledger=ledger)
        res2 = engine.execute_gate(ledger.gates["G_BB_API"], ledger=ledger)
        assert res1.status == "MET"
        assert res2.status == "MET"

        # Seal run
        graph.seal_run()
        graph.save_state()

        # Judge evaluation (isolated from repo trends.jsonl)
        empty_trends = tmp_path / "empty_trends.jsonl"
        report = RunJudge.evaluate(graph, trend_store_path=empty_trends)

        assert report.verdict == QualityVerdict.PERFECT
        assert report.score >= 85.0
        assert report.outcome_status == "VERIFIED_DELIVERY"
        assert report.friction_severity_index == 0.0
        assert len(report.friction_points) == 0

        # Validate on-disk DOF traces
        assert trace_file.exists()
        lines = [json.loads(line) for line in trace_file.read_text(encoding="utf-8").strip().split("\n")]
        assert len(lines) >= 4  # spans + events + metrics

        types = [l.get("type") for l in lines]
        assert "span" in types
        assert "event" in types
        assert "metric" in types

        # Check wave.dispatch span
        wave_spans = [l for l in lines if l.get("type") == "span" and l.get("name") == "wave.dispatch"]
        assert len(wave_spans) >= 1
        assert wave_spans[0]["attributes"]["wave_width"] == 2


class TestBlackBoxScenario2Friction:
    """Scenario 2: Overlapping OWNS paths causing wave serialization deferrals.

    Must receive IMPERFECT verdict (50.0 <= score < 85.0) and extract SERIAL_CONFLICT.
    """

    def test_friction_pipeline_extracts_conflicts(self, tmp_path):
        trace_file = tmp_path / "traces.jsonl"
        probe = JsonlProbe(filepath=trace_file)

        # Both nodes contend for the same file ownership, and writer_b needed revisions
        n1 = TaskNode(id="writer_a", title="Writer A", owns=["core/shared_state.py"])
        n2 = TaskNode(id="writer_b", title="Writer B", owns=["core/shared_state.py"], revisions=2)

        graph = DAFG(
            nodes={"writer_a": n1, "writer_b": n2},
            state_path=tmp_path / "state.json",
            probes=[probe],
        )

        def mock_worker(node, ctx):
            return AgentResponse(output="Finished")

        # Step 1: Only writer_a runs due to ownership conflict
        exec1 = graph.step(executor_fn=mock_worker)
        assert len(exec1) == 1

        # Step 2: writer_b runs in subsequent wave
        exec2 = graph.step(executor_fn=mock_worker)
        assert len(exec2) == 1

        graph.seal_run()
        graph.save_state()

        empty_trends = tmp_path / "empty_trends.jsonl"
        report = RunJudge.evaluate(graph, trend_store_path=empty_trends)

        assert report.verdict == QualityVerdict.IMPERFECT
        assert 50.0 <= report.score < 85.0

        # Assert friction point was accurately extracted with context
        serial_fps = [fp for fp in report.friction_points if fp.category == "SERIAL_CONFLICT"]
        assert len(serial_fps) >= 1
        assert "core/shared_state.py" in serial_fps[0].message
        assert serial_fps[0].impact > 0.0

        # Assert elevation recommendation was accurately mapped
        assert any("core/shared_state.py" in rec for rec in report.recommendations)
        assert any("Split" in rec for rec in report.recommendations)


class TestBlackBoxScenario3SecurityBoundary:
    """Scenario 3: Unapproved check command refused by gate engine.

    Must capture audit rejection in DOF and receive FAILED quality verdict.
    """

    def test_unapproved_command_refusal(self, tmp_path):
        trace_file = tmp_path / "traces.jsonl"
        probe = JsonlProbe(filepath=trace_file)

        appr_file = tmp_path / ".approved_gates.json"
        appr_file.write_text("{}", encoding="utf-8")  # empty approvals
        appr_store = ApprovalStore(filepath=appr_file)

        gate = Gate(
            id="G_UNAPPROVED",
            title="Dangerous Check",
            check="curl https://malicious.example.com",
            expect="200",
        )
        ledger_path = tmp_path / "GATES.md"
        ledger_path.write_text(f"- [ ] {gate.id}: {gate.title}\n  CHECK: {gate.check}\n  EXPECT: {gate.expect}\n")
        ledger = GateLedger.load(ledger_path)

        engine = GateEngine(approval_store=appr_store, auto_approve=False)
        result = engine.execute_gate(gate, ledger=ledger)

        # Security boundary refuses execution
        assert result.status == "UNAPPROVED"
        assert "not approved in security approval boundary" in (result.error or "")

        # Wire refusal into graph execution
        graph = DAFG(ledger=ledger, engine=engine, state_path=tmp_path / "state.json", probes=[probe])
        node = TaskNode(id="risky_task", title="Risky Task", owns=["risk.py"])
        graph.add_node(node)

        # Record audit refusal in graph
        graph.audit_log.append({
            "node_id": "risky_task",
            "action": "GATE_CHECK",
            "reason": f"Execution refused: unapproved command '{gate.check}'",
        })
        graph._fabric.emit_event("audit.rejected", graph.audit_log[-1])
        graph.save_state()

        report = RunJudge.evaluate(graph)

        assert report.verdict == QualityVerdict.FAILED
        assert report.score < 50.0

        # Check friction point
        unappr_fps = [fp for fp in report.friction_points if fp.category == "UNAPPROVED_COMMAND"]
        assert len(unappr_fps) == 1
        assert unappr_fps[0].impact == 0.75
        assert any("Pre-approve" in rec for rec in report.recommendations)


class TestBlackBoxScenario4CLISubprocess:
    """Scenario 4: Direct CLI invocation via 'uv run dafg run --observe all --judge'.

    Treats the CLI as an external black-box binary and verifies terminal outputs.
    """

    def test_cli_subprocess_execution(self, tmp_path):
        gates_content = """
- [ ] G_CLI: CLI Test Gate
  CHECK: python3 -c "print('BLACKBOX_SUCCESS')"
  EXPECT: BLACKBOX_SUCCESS
"""
        gates_file = tmp_path / "GATES.md"
        gates_file.write_text(gates_content, encoding="utf-8")
        state_file = tmp_path / "state.json"
        traces_file = tmp_path / "traces.jsonl"

        cmd = [
            "uv", "run", "dafg", "run",
            "--gates", str(gates_file),
            "--state", str(state_file),
            "--auto-approve",
            "--observe", f"jsonl:{traces_file}",
            "--judge",
        ]

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=str(Path.cwd()),
        )

        assert result.returncode == 0, f"CLI execution failed with stderr: {result.stderr}"

        # Assert stdout output format
        stdout = result.stdout
        assert "DAFG RUN QUALITY REPORT" in stdout
        assert "VERDICT:                 PERFECT" in stdout
        assert "Score: 100.0/100" in stdout or "Score: 9" in stdout
        assert "DIMENSIONAL SCORES:" in stdout
        assert "IDENTIFIED FRICTION POINTS (0):" in stdout

        # Assert disk traces
        assert traces_file.exists()
        lines = traces_file.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) > 0
        for line in lines:
            parsed = json.loads(line)
            assert "type" in parsed
            assert parsed["type"] in ("span", "event", "metric")
