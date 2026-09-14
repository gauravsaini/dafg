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


def test_organism_evolver_sequential_multifire_convergence(tmp_path):
    """Verify OrganismEvolver firing multiple times in sequence across 3 generations:
    Gen 1 -> SERIAL_CONFLICT -> OrganismEvolver fires (pass 1: partitions ownership, scales workers)
    Gen 2 -> REVISION_THRASH -> OrganismEvolver fires (pass 2: injects InterfaceContract, promotes persona)
    Gen 3 -> Converged: Score(Gen 3) > Score(Gen 2) >= Score(Gen 1), FSI(Gen 3) == 0.0, VERIFIED_DELIVERY
    """
    gates_file = tmp_path / "GATES.md"
    state_file = tmp_path / "state.json"
    approvals_file = tmp_path / ".approved_gates.json"

    # Setup 3 gates across an ingestion, transformation, and storage pipeline
    gates_md = (
        "- [ ] G_INGEST: Ingestion verification\n"
        "  CHECK: python3 -c \"print('INGEST_OK')\"\n"
        "  EXPECT: INGEST_OK\n"
        "  OWNS: src/pipeline.py\n\n"
        "- [ ] G_TRANSFORM: Transformation verification\n"
        "  CHECK: python3 -c \"print('TRANSFORM_OK')\"\n"
        "  EXPECT: TRANSFORM_OK\n"
        "  OWNS: src/pipeline.py\n\n"
        "- [ ] G_STORE: Storage verification\n"
        "  CHECK: python3 -c \"print('STORE_OK')\"\n"
        "  EXPECT: STORE_OK\n"
        "  OWNS: src/storage.py\n"
    )
    gates_file.write_text(gates_md, encoding="utf-8")
    ledger = GateLedger.parse(gates_md, filepath=gates_file)

    app_store = ApprovalStore(filepath=approvals_file)
    for g in ledger.gates.values():
        app_store.approve(g)

    engine = GateEngine(approval_store=app_store, auto_approve=False)

    # -------------------------------------------------------------------------
    # GENERATION 1: Severe Serialization Contention (workers 1 & 2 share src/pipeline.py)
    # -------------------------------------------------------------------------
    n1 = TaskNode(id="node_ingest", title="Ingest Task", owns=["src/pipeline.py"], assigned_gates=["G_INGEST"])
    n2 = TaskNode(id="node_transform", title="Transform Task", owns=["src/pipeline.py"], assigned_gates=["G_TRANSFORM"])
    n3 = TaskNode(id="node_store", title="Store Task", owns=["src/storage.py"], assigned_gates=["G_STORE"])

    graph = DAFG(
        nodes={"node_ingest": n1, "node_transform": n2, "node_store": n3},
        ledger=ledger,
        engine=engine,
        state_path=state_file,
        budget=Budget(max_calls=20, max_nodes=10),
    )
    graph.max_parallel_workers = 2

    # Gen 1 executor: completes cleanly, but topology causes SERIAL_CONFLICT deferrals
    def executor_gen1(node, ctx):
        return AgentResponse(output="ok", status="COMPLETED")

    graph.run(executor_fn=executor_gen1)
    report_gen1 = RunJudge.evaluate(graph)

    # Verify Gen 1 suffered SERIAL_CONFLICT on src/pipeline.py
    conflict_fps_gen1 = [fp for fp in report_gen1.friction_points if fp.category == "SERIAL_CONFLICT"]
    assert len(conflict_fps_gen1) >= 1
    assert any("src/pipeline.py" in fp.message or fp.details.get("path") == "src/pipeline.py" for fp in conflict_fps_gen1)

    # -------------------------------------------------------------------------
    # EVOLUTION PASS 1: OrganismEvolver fires after Gen 1
    # -------------------------------------------------------------------------
    mutations_pass1 = OrganismEvolver.evolve(
        graph=graph,
        report=report_gen1,
        ledger=ledger,
    )
    assert len(mutations_pass1) >= 1
    assert any("Partitioned 'src/pipeline.py' ownership" in m for m in mutations_pass1)

    # Verify ownership partitioning succeeded
    assert n1.owns == ["src/pipeline.py"]
    assert any("src/pipeline.py.sub_" in p for p in n2.owns)

    # -------------------------------------------------------------------------
    # GENERATION 2: Partitioning resolved SERIAL_CONFLICT, but un-contracted dependency
    # introduces REVISION_THRASH on node_transform
    # -------------------------------------------------------------------------
    graph.prepare_next_generation(2)

    def executor_gen2(node, ctx):
        # node_transform encounters revision thrash on its first 2 revisions in gen 2 without contract
        if node.id == "node_transform" and node.revisions < 2 and "contract_rev_node_transform" not in graph.contracts:
            return AgentResponse(output="Interface schema mismatch on ingest payload", status="FAILED")
        return AgentResponse(output="ok", status="COMPLETED")

    graph.run(executor_fn=executor_gen2)
    report_gen2 = RunJudge.evaluate(graph)

    # Verify SERIAL_CONFLICT is resolved in Gen 2
    assert not any(fp.category == "SERIAL_CONFLICT" for fp in report_gen2.friction_points)

    # Verify Gen 2 suffered REVISION_THRASH
    thrash_fps_gen2 = [fp for fp in report_gen2.friction_points if fp.category == "REVISION_THRASH"]
    assert len(thrash_fps_gen2) >= 1
    assert n2.revisions >= 1

    # -------------------------------------------------------------------------
    # EVOLUTION PASS 2: OrganismEvolver fires A SECOND TIME IN SEQUENCE after Gen 2
    # -------------------------------------------------------------------------
    mutations_pass2 = OrganismEvolver.evolve(
        graph=graph,
        report=report_gen2,
        ledger=ledger,
    )
    assert len(mutations_pass2) >= 1
    # Mutator injected strict InterfaceContract for the thrashing node
    assert any("Injected strict InterfaceContract" in m and "node_transform" in m for m in mutations_pass2)
    # Mutator promoted persona
    assert any("PersonaEvolution: Promoted node_transform persona" in m for m in mutations_pass2)
    assert "contract_rev_node_transform" in graph.contracts

    # -------------------------------------------------------------------------
    # GENERATION 3: Clean execution under double-evolved topology & contract
    # -------------------------------------------------------------------------
    graph.prepare_next_generation(3)

    def executor_gen3(node, ctx):
        # Under contract_rev_node_transform and promoted specialist persona, execution succeeds first try
        return AgentResponse(output="ok", status="COMPLETED")

    graph.run(executor_fn=executor_gen3)
    report_gen3 = RunJudge.evaluate(graph)

    # -------------------------------------------------------------------------
    # RIGOROUS EMPIRICAL CONVERGENCE ASSERTIONS
    # -------------------------------------------------------------------------
    # 1. Quality convergence across generations
    assert report_gen3.score > report_gen1.score
    assert report_gen3.score > report_gen2.score
    assert report_gen3.verdict == QualityVerdict.PERFECT
    assert report_gen3.outcome_status == OutcomeStatus.VERIFIED_DELIVERY.value

    # 2. Strictly monotonic friction reduction
    assert report_gen3.friction_severity_index < report_gen2.friction_severity_index < report_gen1.friction_severity_index
    assert report_gen3.friction_severity_index == 0.0

    # 3. Both evolutionary passes were distinct and non-empty
    assert len(mutations_pass1) > 0
    assert len(mutations_pass2) > 0
    assert mutations_pass1 != mutations_pass2

    # 4. Zero mutations needed in Gen 3 (converged!)
    mutations_pass3 = OrganismEvolver.evolve(
        graph=graph,
        report=report_gen3,
        ledger=ledger,
    )
    assert len(mutations_pass3) == 0

