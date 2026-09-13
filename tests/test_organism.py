"""Tests for DAFG Autonomous Reactive & Self-Improving Execution Organism.

Verifies the 8 engineering success criteria:
1. Single high-level goal input
2. Autonomous genesis (graph, gates, personas, ownership, test harness)
3. Instantly reactive execution & repair interception
4. Quality evaluation via RunJudge
5. Multi-axis evolutionary mutation across generations
6. Generational improvement (score increase, friction reduction)
7. Autonomous convergence to verified delivery
8. Zero user intervention
"""
import json
from pathlib import Path
import subprocess
import pytest

from dafg.organism import (
    AutonomousOrganism,
    GenerationRecord,
    GoalManifest,
    ModuleSpec,
    OrganismEvolver,
    OrganismGenesis,
    OrganismLineage,
    OrganismReactor,
)
from dafg.judge import (
    FrictionPoint,
    FrictionSeverity,
    QualityDimension,
    QualityVerdict,
    RunJudge,
    RunQualityReport,
)
from dafg.runtime import DAFG, NodeStatus, TaskNode


class TestOrganismGenesis:
    """Test Criterion 1 & 2: Goal decomposition and architectural synthesis."""

    def test_goal_decomposition_redis_clone(self, tmp_path):
        manifest = OrganismGenesis.decompose(
            "Clone Redis key-value store with string, list, and hash commands, TTL expiration, and persistence",
            workdir=tmp_path,
        )
        assert manifest.system_name == "kv_store"
        assert len(manifest.modules) >= 4

        # Check disjoint ownership
        all_owns = []
        for mod in manifest.modules:
            assert len(mod.owns) > 0
            for path in mod.owns:
                assert path not in all_owns, f"Overlapping file ownership detected: {path}"
                all_owns.append(path)

        # Verify roles are domain-specialized
        roles = [m.suggested_role for m in manifest.modules]
        assert "SystemArchitect" in roles
        assert "StorageSpecialist" in roles
        assert "ProtocolEngineer" in roles

    def test_gates_markdown_synthesis_and_scaffolding(self, tmp_path):
        manifest = OrganismGenesis.decompose(
            "Build an in-memory SQL database query engine with indexing",
            workdir=tmp_path,
        )
        gates_md = OrganismGenesis.synthesize_gates_markdown(manifest)
        assert "Acceptance Gates: SQL_ENGINE" in gates_md
        assert manifest.integration_gate_id in gates_md
        assert "OWNS:" in gates_md
        assert "CHECK:" in gates_md
        assert "EXPECT:" in gates_md

        # Scaffold test runner and verify files exist
        test_file = OrganismGenesis.scaffold_test_runner(manifest, tmp_path)
        assert test_file.exists()
        assert (tmp_path / "src" / "core.py").exists()
        assert (tmp_path / "src" / "storage.py").exists()
        assert (tmp_path / "src" / "protocol.py").exists()

        # Run test harness directly
        res = subprocess.run(
            ["uv", "run", "python", str(test_file), "CORE"],
            capture_output=True,
            text=True,
            cwd=str(tmp_path),
        )
        assert res.returncode == 0
        assert "CORE_PASS" in res.stdout


class TestOrganismReactor:
    """Test Criterion 3: Instantly reactive execution & in-flight conflict/failure interception."""

    def test_reactive_gate_failure_interception(self, tmp_path):
        organism = AutonomousOrganism(
            goal="Build a microservice with health and metrics",
            workdir=tmp_path,
        )
        manifest, ledger, graph = organism.bootstrap_genesis()
        reactor = OrganismReactor(graph=graph, ledger=ledger, engine=graph.engine)

        # Artificially fail a gate check
        gate = ledger.gates["G1"]
        gate.check = "uv run python -c 'import sys; sys.exit(1)'"

        handled = reactor.on_gate_failure(gate_id="G1", node=list(graph.nodes.values())[0])
        assert len(reactor.interceptions) > 0
        assert reactor.interceptions[0]["event"] == "GATE_FAILURE_INTERCEPTED"
        assert reactor.interceptions[0]["gate_id"] == "G1"

    def test_reactive_serial_conflict_seam_synthesis(self, tmp_path):
        organism = AutonomousOrganism(
            goal="Build a data cache service",
            workdir=tmp_path,
        )
        manifest, ledger, graph = organism.bootstrap_genesis()
        reactor = OrganismReactor(graph=graph, ledger=ledger, engine=graph.engine)

        node_a = TaskNode("task_A", "Worker A", owns=["src/shared.py"])
        node_b = TaskNode("task_B", "Worker B", owns=["src/shared.py"])
        graph.add_node(node_a)
        graph.add_node(node_b)

        assert len(graph.contracts) == 0
        reactor.on_serial_conflict(node_a, node_b, "src/shared.py")
        assert len(graph.contracts) == 1
        cid = list(graph.contracts.keys())[0]
        assert "task_A" in cid and "task_B" in cid
        assert len(reactor.interceptions) == 1
        assert reactor.interceptions[0]["event"] == "SEAM_SYNTHESIZED"


class TestOrganismEvolver:
    """Test Criterion 5: Multi-axis evolutionary mutation across generations."""

    def test_graph_evolution_partitions_serial_conflicts(self, tmp_path):
        organism = AutonomousOrganism(
            goal="Build a distributed worker pool",
            workdir=tmp_path,
        )
        manifest, ledger, graph = organism.bootstrap_genesis()

        # Add two nodes competing for the same file
        node1 = TaskNode("task_1", "Node 1", owns=["src/worker.py"])
        node2 = TaskNode("task_2", "Node 2", owns=["src/worker.py"])
        graph.add_node(node1)
        graph.add_node(node2)

        # Mock a report indicating serial conflict
        report = RunQualityReport(
            run_id="test_run",
            verdict=QualityVerdict.IMPERFECT,
            score=70.0,
            outcome_status="INCOMPLETE_RUN",
            dimensions={
                "Concurrency Health": QualityDimension(
                    name="Concurrency Health",
                    score=30.0,
                    weight=0.15,
                    summary="Low concurrency",
                )
            },
            friction_points=[
                FrictionPoint(
                    category="SERIAL_CONFLICT",
                    message="OWNS: conflict on 'src/worker.py' forced task deferrals",
                    severity=FrictionSeverity.HIGH,
                    impact=1.0,
                    details={"file_path": "src/worker.py"},
                )
            ],
        )

        mutations = OrganismEvolver.evolve(graph=graph, report=report, ledger=ledger)
        assert len(mutations) >= 1
        # Verify node2's ownership was partitioned
        assert "src/worker.py" not in node2.owns
        assert any(".sub_" in p for p in node2.owns)

    def test_persona_evolution_promotes_troubled_nodes(self, tmp_path):
        organism = AutonomousOrganism(
            goal="Build an encrypted vault service",
            workdir=tmp_path,
        )
        manifest, ledger, graph = organism.bootstrap_genesis()

        # Simulate a node with revisions
        node = list(graph.nodes.values())[0]
        node.revisions = 2
        node.role = "coder"

        report = RunQualityReport(
            run_id="test_run",
            verdict=QualityVerdict.IMPERFECT,
            score=75.0,
            outcome_status="INCOMPLETE_RUN",
            dimensions={},
            friction_points=[
                FrictionPoint(
                    category="REVISION_THRASH",
                    message="Repeated revisions",
                    severity=FrictionSeverity.HIGH,
                    impact=0.8,
                    node_id=node.id,
                )
            ],
        )

        mutations = OrganismEvolver.evolve(graph=graph, report=report, ledger=ledger)
        assert any("PersonaEvolution" in m for m in mutations)
        assert "Principal" in node.role


class TestAutonomousOrganismConvergence:
    """Test Criterion 6, 7 & 8: Generational convergence, lineage, zero intervention."""

    def test_autonomous_organism_end_to_end(self, tmp_path):
        organism = AutonomousOrganism(
            goal="Clone Redis key-value store with string, list, and hash commands",
            workdir=tmp_path,
            max_generations=3,
            target_score=85.0,
        )

        lineage = organism.evolve_to_completion()
        assert lineage.system_name == "kv_store"
        assert len(lineage.generations) >= 1
        assert lineage.converged is True
        assert lineage.final_score >= 85.0

        # Verify lineage persistence
        lineage_file = tmp_path / "lineage.json"
        assert lineage_file.exists()
        saved = json.loads(lineage_file.read_text(encoding="utf-8"))
        assert saved["converged"] is True
        assert saved["final_score"] == lineage.final_score

        # Verify dashboard formatting
        dashboard = organism.format_lineage_dashboard()
        assert "DAFG AUTONOMOUS ORGANISM EVOLUTION DASHBOARD" in dashboard
        assert "Score:" in dashboard
        assert "Gen 1" in dashboard

    def test_cli_organism_command(self, tmp_path):
        out_dir = tmp_path / "cli_organism"
        res = subprocess.run(
            [
                "uv",
                "run",
                "dafg",
                "organism",
                "--goal",
                "Build a high performance caching service with metrics and security",
                "--generations",
                "2",
                "--workdir",
                str(out_dir),
                "--json",
            ],
            capture_output=True,
            text=True,
        )
        assert res.returncode == 0
        data = json.loads(res.stdout)
        assert data["converged"] is True
        assert "generations" in data
        assert len(data["generations"]) >= 1

    def test_multi_generation_evolution_progression(self, tmp_path):
        organism = AutonomousOrganism(
            goal="Build an autonomous messaging bus with priority queues",
            workdir=tmp_path,
            max_generations=2,
            target_score=99.0,  # Unreached in Gen 1 to trigger evolution
        )
        lineage = organism.evolve_to_completion()
        assert len(lineage.generations) == 2
        gen1 = lineage.generations[0]
        assert len(gen1.mutations_applied) > 0
        assert lineage.total_mutations > 0

