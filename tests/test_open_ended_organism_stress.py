"""Stress tests for AutonomousOrganism on genuinely open-ended goals.

Tests that AutonomousOrganism:
1. Decomposes a raw, un-scripted, open-ended goal and evolves across generations
   to find its own path to convergence without any pre-scripted failure sequence.
2. Accurately detects when it gets stuck on persistent defects, refusing false
   convergence and terminating honestly with converged=False.
3. Records complete audit lineages with mutation proposals, Goodhart checks,
   and terminal dashboard formatting.
"""

from pathlib import Path
import json
import pytest

from dafg.organism import (
    AutonomousOrganism,
    EvolutionPolicy,
    GoodhartDetector,
    GoalContract,
    OrganismEvolver,
)
from dafg.mutation import EvolutionMutationType


def test_open_ended_kv_store_natural_convergence(tmp_path):
    """Stress test: A realistic, open-ended goal is given to AutonomousOrganism with zero pre-scripting.

    The organism must:
    1. Bootstrap genesis (decompose into core, storage, protocol, metrics, security + E2E).
    2. Run Generation 1, encounter natural architectural wave contention (SERIAL_CONFLICT)
       between the E2E integration gate and domain modules.
    3. Be BLOCKED from premature convergence by EvolutionPolicy due to FSI >= 0.15.
    4. Autonomously propose graph partitioning mutations.
    5. Advance to Generation 2, resolve contention, reduce FSI to 0.0, and achieve verified convergence.
    6. Persist complete lineage.json with dashboard.
    """
    workdir = tmp_path / "kv_store_organism"
    goal = (
        "Build a high-performance transactional key-value store with string and hash operations, "
        "sliding-window TTL expiration, append-only WAL persistence, and snapshot recovery"
    )

    organism = AutonomousOrganism(
        goal=goal,
        workdir=workdir,
        auto_approve=True,
        max_generations=5,
        target_score=90.0,
    )

    records = []
    lineage = organism.evolve_to_completion(generation_callback=lambda r: records.append(r))

    # Verification of evolutionary progression
    assert lineage.converged is True
    assert lineage.final_score >= 90.0
    assert lineage.final_verdict == "PERFECT"
    assert len(lineage.generations) >= 2, "Must take at least 2 generations to naturally evolve past initial contention"

    gen1 = lineage.generations[0]
    # Gen 1 had contention and imperfect FSI
    assert gen1.friction_severity_index > 0.15, "Gen 1 should have had natural file ownership contention"
    assert any(
        m.startswith("GraphEvolution: Partitioned")
        for m in gen1.mutations_applied
    ), "Gen 1 must autonomously propose graph partitioning"

    # Gen 2 resolved the contention
    gen2 = lineage.generations[1]
    assert gen2.friction_severity_index < 0.15
    assert gen2.score >= gen1.score, "Gen 2 score should improve or match Gen 1"
    assert gen2.gates_met == gen2.gates_total

    # Verify lineage.json was persisted
    lineage_file = workdir / "lineage.json"
    assert lineage_file.exists()
    data = json.loads(lineage_file.read_text(encoding="utf-8"))
    assert data["converged"] is True
    assert len(data["generations"]) == len(lineage.generations)
    assert "mutation_proposals" in data

    # Verify terminal dashboard renders cleanly
    dashboard = organism.format_lineage_dashboard()
    assert "DAFG AUTONOMOUS ORGANISM EVOLUTION DASHBOARD" in dashboard
    assert "Converged:  YES" in dashboard
    assert f"Goal:       {goal}" in dashboard


def test_open_ended_organism_gets_stuck_on_persistent_defect(tmp_path):
    """Stress test: When a hard goal encounters an unresolvable defect,

    the organism must NOT falsely declare convergence. It must:
    1. Detect the failing gate and reject the node.
    2. Promote persona to specialist with sharpened focus.
    3. Block convergence each generation via EvolutionPolicy.
    4. Exhaust max_generations and honestly terminate with converged=False.
    """
    workdir = tmp_path / "broken_service_organism"
    goal = "Build a distributed raft consensus cluster with dynamic membership reconfiguration"

    # Pre-scaffold with a deliberate defect in storage module that causes its test to exit with error
    workdir.mkdir(parents=True, exist_ok=True)
    src_dir = workdir / "src"
    src_dir.mkdir(parents=True, exist_ok=True)
    storage_file = src_dir / "storage.py"
    # Broken storage file that raises a fatal exception on import/call
    storage_file.write_text(
        "raise RuntimeError('STORAGE_CRITICAL_CORRUPTION: disk unreadable')\n",
        encoding="utf-8",
    )

    policy = EvolutionPolicy(target_score=90.0, max_generations=3)
    organism = AutonomousOrganism(
        goal=goal,
        workdir=workdir,
        auto_approve=True,
        evolution_policy=policy,
    )

    lineage = organism.evolve_to_completion()

    # Must NOT converge because storage gate fails
    assert lineage.converged is False
    assert len(lineage.generations) == 3

    # Check that mutations attempted persona promotion or interface contract injection
    all_mutations = [m for g in lineage.generations for m in g.mutations_applied]
    assert any("PersonaEvolution" in m or "GraphEvolution" in m for m in all_mutations)

    # Lineage reflects honest non-convergence
    lineage_file = workdir / "lineage.json"
    assert lineage_file.exists()
    data = json.loads(lineage_file.read_text(encoding="utf-8"))
    assert data["converged"] is False

    dashboard = organism.format_lineage_dashboard()
    assert "Converged:  NO (Max Generations)" in dashboard


def test_open_ended_anti_goodhart_veto_preserves_contract(tmp_path):
    """Stress test: Anti-Goodhart contract challenger blocks illegal mutations across generations."""
    workdir = tmp_path / "contract_guarded_organism"
    goal = "Build an enterprise authentication and token rotation service"

    organism = AutonomousOrganism(
        goal=goal,
        workdir=workdir,
        auto_approve=True,
        max_generations=2,
    )

    manifest, ledger, graph = organism.bootstrap_genesis()
    assert manifest.goal_contract is not None

    # Simulate an illegal tampering with invariant gate G1 (dropping check command)
    g1 = ledger.get_gate("G1")
    assert g1 is not None
    original_check = g1.check
    g1.check = "true"  # Vacuous check

    valid, violations = manifest.goal_contract.validate_ledger(ledger)
    assert valid is False
    assert any("vacuous check command" in v for v in violations)

    # OrganismEvolver must issue an ANTI_GOODHART_VETO
    from dafg.judge import RunJudge
    report = RunJudge.evaluate(graph)
    proposal = OrganismEvolver.evolve_proposal(
        graph=graph,
        report=report,
        ledger=ledger,
        goal_contract=manifest.goal_contract,
        generation=1,
    )

    assert len(proposal.vetoes) >= 1
    assert proposal.vetoes[0].mutation_type == EvolutionMutationType.ANTI_GOODHART_VETO
    assert "Refused illegal mutation" in proposal.vetoes[0].description


def test_open_ended_organism_defect_recovery_across_generations(tmp_path):
    """Stress test: Organism recovers from a Gen 1 defect when code is corrected in Gen 2.

    Demonstrates:
    Gen 1: Defect causes gate failure, persona promotion occurs, convergence is blocked.
    Gen 2: Defect is repaired, all gates pass, friction drops, convergence succeeds.
    """
    workdir = tmp_path / "defect_recovery_organism"
    goal = "Build a high-throughput event streaming pipeline with windowed aggregations"

    # Pre-scaffold a broken module in src/protocol.py
    workdir.mkdir(parents=True, exist_ok=True)
    src_dir = workdir / "src"
    src_dir.mkdir(parents=True, exist_ok=True)
    protocol_file = src_dir / "protocol.py"
    protocol_file.write_text("raise SyntaxError('Unparsable protocol specification')\n", encoding="utf-8")

    organism = AutonomousOrganism(
        goal=goal,
        workdir=workdir,
        auto_approve=True,
        max_generations=4,
    )

    def on_generation(record):
        # When Gen 1 completes with failure, simulate the agent/developer fixing the defect
        if record.generation == 1:
            protocol_file.write_text(
                '"""Repaired protocol module."""\n\ndef parse_command(cmd):\n    return {"parsed": cmd}\n\ndef init_protocol():\n    return {"status": "ok"}\n',
                encoding="utf-8",
            )

    lineage = organism.evolve_to_completion(generation_callback=on_generation)

    # Must converge by Gen 2 or Gen 3
    assert lineage.converged is True
    assert len(lineage.generations) >= 2

    # Gen 1 failed due to the syntax error
    gen1 = lineage.generations[0]
    assert gen1.gates_met < gen1.gates_total

    # Later generation succeeded after the fix
    last_gen = lineage.generations[-1]
    assert last_gen.gates_met == last_gen.gates_total
    assert last_gen.score > gen1.score
    assert last_gen.friction_severity_index < 0.15

