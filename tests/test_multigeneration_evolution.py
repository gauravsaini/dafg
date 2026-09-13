"""Tests for Invariant I7: Multi-Generation Causal Evolution and Defect Resolution."""

import json
from pathlib import Path
import pytest

from dafg.runtime import (
    DAFG,
    TaskNode,
    NodeStatus,
    Budget,
    AgentResponse,
    OutcomeStatus,
)
from dafg.gates import Gate, GateLedger, GateEngine, ApprovalStore
from dafg.judge import RunJudge, QualityVerdict
from dafg.organism import OrganismEvolver


def test_multigeneration_causal_evolution_resolves_serial_conflict(tmp_path):
    """Assert multi-generation progression:
    Gen 1: Seeded architectural defect (SERIAL_CONFLICT on 'src/core.py' with forced deferrals)
    Gen 2: Causal mutation partitions ownership, removing contention
    Gen 3: Convergence with verified delivery, 0 deferrals, and Score(Gen 2) > Score(Gen 1).
    """
    gates_file = tmp_path / "GATES.md"
    state_file = tmp_path / "state.json"
    approvals_file = tmp_path / ".approved_gates.json"

    # Setup 2 gates
    g1 = Gate(id="G1", title="Core Feature 1", check="python3 -c \"print('G1_OK')\"", expect="G1_OK", status="PENDING")
    g2 = Gate(id="G2", title="Core Feature 2", check="python3 -c \"print('G2_OK')\"", expect="G2_OK", status="PENDING")

    gates_md = (
        "- [ ] G1: Core Feature 1\n"
        "  CHECK: python3 -c \"print('G1_OK')\"\n"
        "  EXPECT: G1_OK\n"
        "  OWNS: src/core.py\n\n"
        "- [ ] G2: Core Feature 2\n"
        "  CHECK: python3 -c \"print('G2_OK')\"\n"
        "  EXPECT: G2_OK\n"
        "  OWNS: src/core.py\n"
    )
    gates_file.write_text(gates_md, encoding="utf-8")
    ledger = GateLedger.parse(gates_md, filepath=gates_file)

    app_store = ApprovalStore(filepath=approvals_file)
    app_store.approve(g1)
    app_store.approve(g2)

    engine = GateEngine(approval_store=app_store, auto_approve=False)

    # -------------------------------------------------------------------------
    # GENERATION 1: Seeded Architectural Defect (Overlapping file ownership on src/core.py)
    # -------------------------------------------------------------------------
    n1 = TaskNode(id="worker_1", title="Worker 1", owns=["src/core.py"], assigned_gates=["G1"])
    n2 = TaskNode(id="worker_2", title="Worker 2", owns=["src/core.py"], assigned_gates=["G2"])

    graph_gen1 = DAFG(
        nodes={"worker_1": n1, "worker_2": n2},
        ledger=ledger,
        engine=engine,
        state_path=state_file,
        budget=Budget(max_calls=10, max_nodes=10),
    )
    graph_gen1.max_parallel_workers = 2

    # Run Gen 1
    def executor_gen1(node, ctx):
        return AgentResponse(output="ok", status="COMPLETED")

    graph_gen1.run(executor_fn=executor_gen1)

    # Gen 1 Evaluation
    report_gen1 = RunJudge.evaluate(graph_gen1)
    
    # Assert Gen 1 has friction points containing SERIAL_CONFLICT on src/core.py
    conflict_fps = [fp for fp in report_gen1.friction_points if fp.category == "SERIAL_CONFLICT"]
    assert len(conflict_fps) >= 1
    assert any("src/core.py" in fp.message or fp.details.get("path") == "src/core.py" for fp in conflict_fps)
    
    # Assert Gen 1 deferrals occurred due to file ownership collision
    analytics_gen1 = graph_gen1.get_run_analytics()
    assert analytics_gen1.get("concurrency", {}).get("domain_deferrals", 0) > 0

    # -------------------------------------------------------------------------
    # EVOLUTION: OrganismEvolver analyzes Gen 1 friction and applies causal mutation
    # -------------------------------------------------------------------------
    mutations = OrganismEvolver.evolve(
        graph=graph_gen1,
        report=report_gen1,
        ledger=ledger,
    )
    assert len(mutations) >= 1
    assert any("Partitioned 'src/core.py' ownership" in m for m in mutations)

    # Verify n2 ownership was partitioned away from n1's src/core.py
    assert n1.owns == ["src/core.py"]
    assert n2.owns != ["src/core.py"]
    assert any("src/core.py.sub_" in p for p in n2.owns)

    # -------------------------------------------------------------------------
    # GENERATION 2: Clean execution under evolved graph structure
    # -------------------------------------------------------------------------
    # Reset graph for Generation 2 under evolved topology
    graph_gen1.prepare_next_generation(2)
    graph_gen1.run(executor_fn=executor_gen1)
    report_gen2 = RunJudge.evaluate(graph_gen1)

    # -------------------------------------------------------------------------
    # ASSERT CAUSAL LINK & GENERATIONAL IMPROVEMENT (Invariant I7)
    # -------------------------------------------------------------------------
    # 1. Defect resolved: Zero SERIAL_CONFLICT friction points in Gen 2
    conflict_fps_gen2 = [fp for fp in report_gen2.friction_points if fp.category == "SERIAL_CONFLICT"]
    assert len(conflict_fps_gen2) == 0

    # 2. Concurrency improved: 0 domain deferrals in Gen 2
    analytics_gen2 = graph_gen1.get_run_analytics()
    assert analytics_gen2.get("concurrency", {}).get("domain_deferrals", 0) == 0

    # 3. Score strictly improved: Score(Gen 2) > Score(Gen 1)
    assert report_gen2.score > report_gen1.score

    # 4. Clean delivery outcome
    assert report_gen2.outcome_status == OutcomeStatus.VERIFIED_DELIVERY.value
