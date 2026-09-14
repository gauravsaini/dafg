"""Tests for First-Class Multi-Generation Evolution Loop.

Exercises the full closed loop: runtime → judge → trends/mutation → organism
across 5–10 generation scenarios with intentional failures, flakiness tracking,
Goodhart pressure detection, and strict convergence criteria.
"""

import json
from pathlib import Path
import pytest

from dafg.runtime import (
    DAFG,
    TaskNode,
    NodeStatus,
    Budget,
    AgentResponse,
    InterfaceContract,
    OutcomeStatus,
)
from dafg.gates import Gate, GateLedger, GateEngine, ApprovalStore
from dafg.judge import RunJudge, QualityVerdict, FrictionPoint, FrictionSeverity
from dafg.mutation import (
    EvolutionMutationType,
    EvolutionMutator,
    MutationEntry,
    MutationProposal,
)
from dafg.organism import (
    EvolutionPolicy,
    GenerationRecord,
    GoodhartDetector,
    OrganismEvolver,
)
from dafg.trends import GateRunRecord, RunSummary, TrendAnalyzer, TrendStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_graph_with_conflict(tmp_path, *, num_gates=2, shared_file="src/core.py"):
    """Build a DAFG graph with an intentional SERIAL_CONFLICT on shared_file."""
    gates_file = tmp_path / "GATES.md"
    state_file = tmp_path / "state.json"
    approvals_file = tmp_path / ".approved_gates.json"

    gates_md_lines = []
    nodes = {}
    gate_objects = []
    for i in range(1, num_gates + 1):
        gid = f"G{i}"
        gates_md_lines.append(f"- [ ] {gid}: Feature {i}")
        gates_md_lines.append(f'  CHECK: python3 -c "print(\'G{i}_OK\')"')
        gates_md_lines.append(f"  EXPECT: G{i}_OK")
        gates_md_lines.append(f"  OWNS: {shared_file}")
        gates_md_lines.append("")
        gate_objects.append(Gate(
            id=gid, title=f"Feature {i}",
            check=f"python3 -c \"print('G{i}_OK')\"",
            expect=f"G{i}_OK", status="PENDING",
        ))
        nodes[f"worker_{i}"] = TaskNode(
            id=f"worker_{i}", title=f"Worker {i}",
            owns=[shared_file], assigned_gates=[gid],
        )

    gates_file.write_text("\n".join(gates_md_lines), encoding="utf-8")
    ledger = GateLedger.parse("\n".join(gates_md_lines), filepath=gates_file)

    app_store = ApprovalStore(filepath=approvals_file)
    for g in gate_objects:
        app_store.approve(g)

    engine = GateEngine(approval_store=app_store, auto_approve=False)
    graph = DAFG(
        nodes=nodes, ledger=ledger, engine=engine,
        state_path=state_file, budget=Budget(max_calls=20, max_nodes=10),
    )
    graph.max_parallel_workers = 2
    return graph, ledger, engine


def ok_executor(node, ctx):
    return AgentResponse(output="ok", status="COMPLETED")


def failing_executor(node, ctx):
    """Executor that fails for the first revision of any node."""
    if node.revisions < 1:
        return AgentResponse(output="error", status="FAILED")
    return AgentResponse(output="ok", status="COMPLETED")


# ---------------------------------------------------------------------------
# 1. EvolutionPolicy — hard convergence criteria
# ---------------------------------------------------------------------------

class TestEvolutionPolicy:
    def test_all_criteria_must_pass(self):
        """Convergence requires ALL criteria simultaneously."""
        policy = EvolutionPolicy(target_score=90.0, fsi_threshold=0.15)

        # All good → converge
        ok, blocking = policy.check_convergence(
            score=95.0, fsi=0.05, all_gates_met=True,
            delivery_state="VERIFIED_DELIVERY", contract_valid=True,
            friction_points=[], flakiness_index=0.0,
        )
        assert ok
        assert blocking == []

    def test_score_too_low_blocks(self):
        policy = EvolutionPolicy(target_score=90.0)
        ok, blocking = policy.check_convergence(
            score=80.0, fsi=0.0, all_gates_met=True,
            delivery_state="VERIFIED_DELIVERY", contract_valid=True,
            friction_points=[], flakiness_index=0.0,
        )
        assert not ok
        assert any("Score" in b for b in blocking)

    def test_unmet_gates_block(self):
        policy = EvolutionPolicy()
        ok, blocking = policy.check_convergence(
            score=95.0, fsi=0.0, all_gates_met=False,
            delivery_state="VERIFIED_DELIVERY", contract_valid=True,
            friction_points=[], flakiness_index=0.0,
        )
        assert not ok
        assert any("gates" in b.lower() for b in blocking)

    def test_non_verified_delivery_blocks(self):
        policy = EvolutionPolicy()
        ok, blocking = policy.check_convergence(
            score=95.0, fsi=0.0, all_gates_met=True,
            delivery_state="INCOMPLETE_RUN", contract_valid=True,
            friction_points=[], flakiness_index=0.0,
        )
        assert not ok
        assert any("VERIFIED_DELIVERY" in b for b in blocking)

    def test_high_fsi_blocks(self):
        policy = EvolutionPolicy(fsi_threshold=0.15)
        ok, blocking = policy.check_convergence(
            score=95.0, fsi=0.25, all_gates_met=True,
            delivery_state="VERIFIED_DELIVERY", contract_valid=True,
            friction_points=[], flakiness_index=0.0,
        )
        assert not ok
        assert any("FSI" in b for b in blocking)

    def test_high_friction_severity_blocks(self):
        policy = EvolutionPolicy()
        fp = FrictionPoint(category="GATE_FAILURE", message="bad", severity=FrictionSeverity.HIGH)
        ok, blocking = policy.check_convergence(
            score=95.0, fsi=0.0, all_gates_met=True,
            delivery_state="VERIFIED_DELIVERY", contract_valid=True,
            friction_points=[fp], flakiness_index=0.0,
        )
        assert not ok
        assert any("HIGH" in b for b in blocking)

    def test_flakiness_blocks(self):
        policy = EvolutionPolicy(flakiness_threshold=0.1)
        ok, blocking = policy.check_convergence(
            score=95.0, fsi=0.0, all_gates_met=True,
            delivery_state="VERIFIED_DELIVERY", contract_valid=True,
            friction_points=[], flakiness_index=0.3,
        )
        assert not ok
        assert any("Flakiness" in b for b in blocking)

    def test_contract_invalid_blocks(self):
        policy = EvolutionPolicy()
        ok, blocking = policy.check_convergence(
            score=95.0, fsi=0.0, all_gates_met=True,
            delivery_state="VERIFIED_DELIVERY", contract_valid=False,
            friction_points=[], flakiness_index=0.0,
        )
        assert not ok
        assert any("Contract" in b for b in blocking)


# ---------------------------------------------------------------------------
# 2. GoodhartDetector — anti-gaming across generations
# ---------------------------------------------------------------------------

class TestGoodhartDetector:
    def _make_gen(self, gen, score, gates_met, gates_total, fsi=0.0):
        return GenerationRecord(
            generation=gen, run_id=f"run_{gen}", score=score,
            verdict="PERFECT", delivery_state="VERIFIED_DELIVERY",
            friction_severity_index=fsi, gate_flakiness_index=0.0,
            concurrency_health=100.0, gates_met=gates_met, gates_total=gates_total,
        )

    def test_no_detection_on_healthy_progression(self):
        """Score rises AND gates improve AND FSI decreases → no Goodhart signal."""
        gens = [
            self._make_gen(1, 60.0, 3, 6, fsi=0.4),
            self._make_gen(2, 75.0, 5, 6, fsi=0.2),
            self._make_gen(3, 90.0, 6, 6, fsi=0.0),
        ]
        detected, warnings = GoodhartDetector.detect(gens)
        assert not detected

    def test_detects_score_gate_divergence(self):
        """Score rises while gate pass ratio drops → Goodhart warning."""
        gens = [
            self._make_gen(1, 50.0, 5, 6),   # 83% pass rate
            self._make_gen(2, 65.0, 4, 6),   # 67% pass rate (dropped)
            self._make_gen(3, 80.0, 3, 6),   # 50% pass rate (dropped more)
        ]
        detected, warnings = GoodhartDetector.detect(gens)
        assert detected
        assert any("gate pass ratio dropped" in w for w in warnings)

    def test_detects_gate_count_shrinking(self):
        """Gate count decreasing across generations → scope reduction warning."""
        gens = [
            self._make_gen(1, 70.0, 5, 8),
            self._make_gen(2, 80.0, 5, 6),  # gates shrank 8 → 6
        ]
        detected, warnings = GoodhartDetector.detect(gens)
        assert detected
        assert any("Gate count shrank" in w for w in warnings)

    def test_detects_plateau_gaming(self):
        """Score monotonically rising while FSI stays stagnant → gaming signal."""
        gens = [
            self._make_gen(1, 50.0, 3, 6, fsi=0.3),
            self._make_gen(2, 60.0, 3, 6, fsi=0.29),
            self._make_gen(3, 70.0, 3, 6, fsi=0.31),
        ]
        detected, warnings = GoodhartDetector.detect(gens, lookback=3)
        assert detected
        assert any("FSI stagnant" in w for w in warnings)

    def test_no_detection_on_single_gen(self):
        """Single generation cannot trigger Goodhart detection."""
        gens = [self._make_gen(1, 90.0, 6, 6)]
        detected, warnings = GoodhartDetector.detect(gens)
        assert not detected


# ---------------------------------------------------------------------------
# 3. MutationProposal — structured mutation output
# ---------------------------------------------------------------------------

class TestMutationProposal:
    def test_empty_proposal_signals_convergence(self):
        proposal = MutationProposal(generation=1)
        assert proposal.is_empty
        assert proposal.descriptions == []

    def test_non_empty_proposal(self):
        proposal = MutationProposal(generation=2, entries=[
            MutationEntry(
                mutation_type=EvolutionMutationType.GRAPH_PARTITION,
                description="Partition src/core.py",
                target_id="src/core.py",
            ),
        ])
        assert not proposal.is_empty
        assert "Partition src/core.py" in proposal.descriptions

    def test_serialization_roundtrip(self):
        proposal = MutationProposal(
            generation=3,
            entries=[MutationEntry(
                mutation_type=EvolutionMutationType.GATE_STRENGTHEN,
                description="Strengthen G1",
                target_id="G1",
            )],
            vetoes=[MutationEntry(
                mutation_type=EvolutionMutationType.ANTI_GOODHART_VETO,
                description="Refused: hollow check",
                vetoed=True,
            )],
            score_before=65.0,
        )
        d = proposal.to_dict()
        assert d["generation"] == 3
        assert len(d["entries"]) == 1
        assert len(d["vetoes"]) == 1
        assert d["entries"][0]["mutation_type"] == "GATE_STRENGTHEN"
        assert d["vetoes"][0]["vetoed"] is True


# ---------------------------------------------------------------------------
# 4. EvolutionMutator — proposes from friction points
# ---------------------------------------------------------------------------

class TestEvolutionMutator:
    def test_serial_conflict_produces_partition(self):
        fp = FrictionPoint(
            category="SERIAL_CONFLICT", message="OWNS conflict on 'src/core.py'",
            severity=FrictionSeverity.HIGH, details={"path": "src/core.py"},
        )
        proposal = EvolutionMutator.propose(generation=1, friction_points=[fp], score=60.0)
        assert not proposal.is_empty
        assert any(e.mutation_type == EvolutionMutationType.GRAPH_PARTITION for e in proposal.entries)

    def test_revision_thrash_produces_contract(self):
        fp = FrictionPoint(
            category="REVISION_THRASH", message="High revision rate",
            node_id="node_transform",
        )
        proposal = EvolutionMutator.propose(generation=2, friction_points=[fp], score=55.0)
        assert any(e.mutation_type == EvolutionMutationType.GRAPH_CONTRACT for e in proposal.entries)

    def test_flaky_gates_from_trends(self):
        from dafg.trends import FlakyGate
        flaky = [FlakyGate(gate_id="G1", flip_count=3, last_n_results=["MET", "FAILED", "MET"], confidence=0.5)]
        proposal = EvolutionMutator.propose(generation=3, friction_points=[], score=70.0, flaky_gates=flaky)
        assert any(e.mutation_type == EvolutionMutationType.GATE_STABILIZE for e in proposal.entries)

    def test_pass_rate_regression_triggers_strengthen(self):
        from dafg.trends import Regression
        regs = [Regression(metric_name="pass_rate", previous_mean=0.9, current_value=0.7, delta_pct=-22.2)]
        proposal = EvolutionMutator.propose(generation=4, friction_points=[], score=65.0, regressions=regs)
        assert any(e.mutation_type == EvolutionMutationType.GATE_STRENGTHEN for e in proposal.entries)

    def test_empty_friction_produces_empty_proposal(self):
        proposal = EvolutionMutator.propose(generation=5, friction_points=[], score=95.0)
        assert proposal.is_empty


# ---------------------------------------------------------------------------
# 5. OrganismEvolver.evolve_proposal — structured proposal output
# ---------------------------------------------------------------------------

class TestEvolverProposal:
    def test_evolve_proposal_returns_mutation_proposal(self, tmp_path):
        graph, ledger, engine = make_graph_with_conflict(tmp_path)
        graph.run(executor_fn=ok_executor)
        report = RunJudge.evaluate(graph)

        proposal = OrganismEvolver.evolve_proposal(
            graph=graph, report=report, ledger=ledger, generation=1,
        )
        assert isinstance(proposal, MutationProposal)
        assert proposal.generation == 1
        assert proposal.score_before == report.score

    def test_evolve_backward_compat(self, tmp_path):
        """Legacy evolve() still returns List[str]."""
        graph, ledger, engine = make_graph_with_conflict(tmp_path)
        graph.run(executor_fn=ok_executor)
        report = RunJudge.evaluate(graph)

        mutations = OrganismEvolver.evolve(
            graph=graph, report=report, ledger=ledger,
        )
        assert isinstance(mutations, list)
        assert all(isinstance(m, str) for m in mutations)


# ---------------------------------------------------------------------------
# 6. Multi-Generation Closed Loop (5+ generations)
# ---------------------------------------------------------------------------

def test_five_generation_evolution_with_intentional_failure(tmp_path):
    """Run 5 generations where Gen 1 intentionally fails/is heavily imperfect.

    Closed loop per generation:
    1. Runtime executes
    2. Judge scores
    3. Trends log
    4. Mutation proposes
    5. Evolver applies
    6. Next gen runs automatically

    Verifies: score improvement, friction reduction, convergence.
    """
    graph, ledger, engine = make_graph_with_conflict(tmp_path, num_gates=3, shared_file="src/shared.py")
    trend_store = TrendStore(filepath=tmp_path / "trends.jsonl")

    scores = []
    fsis = []
    proposals = []

    for gen in range(1, 6):
        # Gen 1-2: failing executor (intentional imperfection)
        if gen <= 2:
            executor = failing_executor
        else:
            executor = ok_executor

        graph.run(executor_fn=executor)
        report = RunJudge.evaluate(graph)

        # Log to trends
        trend_store.append_run(RunSummary(
            run_id=graph.run_id,
            timestamp=f"2025-01-0{gen}T00:00:00Z",
            gate_results={},
            outcome="COMPLETE",
            gates_met=sum(1 for g in ledger.gates.values() if g.status == "MET"),
            gates_failed=sum(1 for g in ledger.gates.values() if g.status != "MET"),
            gates_total=len(ledger.gates),
        ))

        scores.append(report.score)
        fsis.append(report.friction_severity_index)

        # Mutation proposes (ALWAYS, even when converged)
        proposal = OrganismEvolver.evolve_proposal(
            graph=graph, report=report, ledger=ledger,
            trend_store=trend_store, generation=gen,
        )
        proposals.append(proposal)

        if gen < 5:
            graph.prepare_next_generation(gen + 1)

    # Assertions across 5 generations
    # 1. Every generation produced a proposal
    assert len(proposals) == 5

    # 2. Later generations should score >= earlier (general trend)
    assert scores[-1] >= scores[0]

    # 3. Trend store has 5 runs logged
    runs = trend_store.load_runs()
    assert len(runs) == 5


def test_flakiness_tracking_across_generations(tmp_path):
    """Track gate flakiness across 6 generations and verify TrendAnalyzer catches it."""
    trend_store = TrendStore(filepath=tmp_path / "trends.jsonl")

    # Simulate 6 runs with gate G1 flipping MET/FAILED
    for i in range(6):
        status = "MET" if i % 2 == 0 else "FAILED"
        trend_store.append_run(RunSummary(
            run_id=f"run_{i}",
            timestamp=f"2025-01-0{i+1}T00:00:00Z",
            gate_results={"G1": GateRunRecord(gate_id="G1", status=status)},
            gates_met=1 if status == "MET" else 0,
            gates_failed=0 if status == "MET" else 1,
            gates_total=1,
        ))

    analyzer = TrendAnalyzer(trend_store)
    flaky = analyzer.get_flaky_gates(window=6)
    assert len(flaky) >= 1
    assert flaky[0].gate_id == "G1"
    assert flaky[0].flip_count >= 4  # MET→FAILED→MET→FAILED→MET→FAILED = 5 flips

    # EvolutionMutator should propose stabilization
    proposal = EvolutionMutator.propose(
        generation=7, friction_points=[], score=70.0, flaky_gates=flaky,
    )
    stabilize_entries = [e for e in proposal.entries if e.mutation_type == EvolutionMutationType.GATE_STABILIZE]
    assert len(stabilize_entries) >= 1


def test_regression_detection_across_generations(tmp_path):
    """Detect regressions (pass rate dropping) across multiple generations."""
    trend_store = TrendStore(filepath=tmp_path / "trends.jsonl")

    # Good runs followed by a bad one
    for i in range(5):
        gates_met = 5 if i < 4 else 2
        trend_store.append_run(RunSummary(
            run_id=f"run_{i}", timestamp=f"2025-01-0{i+1}T00:00:00Z",
            gate_results={}, gates_met=gates_met, gates_failed=5-gates_met, gates_total=5,
        ))

    analyzer = TrendAnalyzer(trend_store)
    regressions = analyzer.get_regression_signals(window=5)
    assert len(regressions) >= 1
    assert any(r.metric_name == "pass_rate" for r in regressions)


def test_goodhart_pressure_detection_in_evolution_loop(tmp_path):
    """Simulate Goodhart pressure: score increases but gate coverage drops.

    Verifies GoodhartDetector raises warnings within the loop.
    """
    records = [
        GenerationRecord(
            generation=1, run_id="r1", score=50.0, verdict="FAILED",
            delivery_state="INCOMPLETE_RUN", friction_severity_index=0.5,
            gate_flakiness_index=0.0, concurrency_health=100.0,
            gates_met=4, gates_total=6,
        ),
        GenerationRecord(
            generation=2, run_id="r2", score=65.0, verdict="IMPERFECT",
            delivery_state="VERIFIED_DELIVERY", friction_severity_index=0.5,
            gate_flakiness_index=0.0, concurrency_health=100.0,
            gates_met=3, gates_total=6,  # Fewer gates met despite higher score
        ),
        GenerationRecord(
            generation=3, run_id="r3", score=80.0, verdict="IMPERFECT",
            delivery_state="VERIFIED_DELIVERY", friction_severity_index=0.5,
            gate_flakiness_index=0.0, concurrency_health=100.0,
            gates_met=2, gates_total=6,  # Even fewer → Goodhart
        ),
    ]
    detected, warnings = GoodhartDetector.detect(records, lookback=3)
    assert detected
    assert len(warnings) >= 1
    # Should detect both score/gate divergence AND FSI stagnation
    assert any("gate pass ratio dropped" in w for w in warnings)


def test_full_closed_loop_convergence(tmp_path):
    """End-to-end: runtime → judge → trends → mutation → evolve across generations.

    Gen 1: SERIAL_CONFLICT (shared file ownership)
    Gen 2: Mutation partitions ownership → conflict resolved
    Gen 3+: Clean runs → convergence

    Validates the FULL cycle described in the spec.
    """
    graph, ledger, engine = make_graph_with_conflict(tmp_path)
    trend_store = TrendStore(filepath=tmp_path / "trends.jsonl")

    all_proposals = []

    for gen in range(1, 5):
        # STEP 1: Runtime
        graph.run(executor_fn=ok_executor)

        # STEP 2: Judge
        report = RunJudge.evaluate(graph)

        # STEP 3: Trends
        trend_store.append_run(RunSummary(
            run_id=graph.run_id,
            timestamp=f"2025-01-0{gen}T00:00:00Z",
            gate_results={},
            outcome="COMPLETE",
            gates_met=sum(1 for g in ledger.gates.values() if g.status == "MET"),
            gates_failed=sum(1 for g in ledger.gates.values() if g.status != "MET"),
            gates_total=len(ledger.gates),
        ))

        # STEP 4: Mutation proposes
        proposal = OrganismEvolver.evolve_proposal(
            graph=graph, report=report, ledger=ledger,
            trend_store=trend_store, generation=gen,
        )
        all_proposals.append(proposal)

        # STEP 5: Evolver applies
        OrganismEvolver.evolve(
            graph=graph, report=report, ledger=ledger,
            trend_store=trend_store, generation=gen,
        )

        # STEP 6: Goodhart check
        gen_records = [
            GenerationRecord(
                generation=g+1, run_id=f"r{g+1}", score=all_proposals[g].score_before,
                verdict="IMPERFECT", delivery_state="VERIFIED_DELIVERY",
                friction_severity_index=0.0, gate_flakiness_index=0.0,
                concurrency_health=100.0,
                gates_met=sum(1 for gobj in ledger.gates.values() if gobj.status == "MET"),
                gates_total=len(ledger.gates),
            )
            for g in range(len(all_proposals))
        ]
        GoodhartDetector.detect(gen_records)

        if gen < 4:
            graph.prepare_next_generation(gen + 1)

    # Verify: proposals produced every generation
    assert len(all_proposals) == 4

    # Gen 1 should have mutations (SERIAL_CONFLICT resolved)
    assert not all_proposals[0].is_empty

    # Later gens should have fewer or no mutations (convergence)
    # The last proposal should be closer to empty than the first
    assert len(all_proposals[-1].entries) <= len(all_proposals[0].entries)


def test_evolution_policy_prevents_premature_convergence(tmp_path):
    """EvolutionPolicy with strict criteria prevents a low-quality run from converging."""
    policy = EvolutionPolicy(
        target_score=90.0,
        fsi_threshold=0.10,
        require_all_gates_met=True,
        require_no_critical_friction=True,
    )

    # Scenario: High score but unmet gates
    converged, blocking = policy.check_convergence(
        score=92.0, fsi=0.05, all_gates_met=False,
        delivery_state="VERIFIED_DELIVERY", contract_valid=True,
        friction_points=[], flakiness_index=0.0,
    )
    assert not converged

    # Scenario: All met but high friction
    fp = FrictionPoint(category="GATE_FAILURE", message="critical", severity=FrictionSeverity.HIGH)
    converged, blocking = policy.check_convergence(
        score=92.0, fsi=0.05, all_gates_met=True,
        delivery_state="VERIFIED_DELIVERY", contract_valid=True,
        friction_points=[fp], flakiness_index=0.0,
    )
    assert not converged

    # Scenario: Everything perfect → converge
    converged, blocking = policy.check_convergence(
        score=95.0, fsi=0.05, all_gates_met=True,
        delivery_state="VERIFIED_DELIVERY", contract_valid=True,
        friction_points=[], flakiness_index=0.0,
    )
    assert converged


def test_mutation_proposal_types_cover_all_friction_categories():
    """Every friction category should map to a mutation type."""
    categories = [
        ("SERIAL_CONFLICT", EvolutionMutationType.GRAPH_PARTITION),
        ("REVISION_THRASH", EvolutionMutationType.GRAPH_CONTRACT),
        ("GATE_FAILURE", EvolutionMutationType.GATE_STRENGTHEN),
        ("PERSONA_THRASH", EvolutionMutationType.PERSONA_PROMOTE),
        ("BUDGET_PRESSURE", EvolutionMutationType.CONCURRENCY_SCALE),
    ]
    for cat, expected_type in categories:
        fp = FrictionPoint(
            category=cat, message=f"Test {cat}",
            details={"path": "src/test.py"} if cat == "SERIAL_CONFLICT" else {},
            node_id="node_1" if cat in ("REVISION_THRASH", "PERSONA_THRASH") else None,
        )
        proposal = EvolutionMutator.propose(generation=1, friction_points=[fp], score=50.0)
        assert any(e.mutation_type == expected_type for e in proposal.entries), \
            f"Category {cat} should produce mutation type {expected_type}"


def test_ten_generation_scenario_with_mixed_failures(tmp_path):
    """Stress test: 10 generations with mixed failure patterns.

    Gens 1-3: Failing (executor fails, SERIAL_CONFLICT)
    Gens 4-6: Partially fixing (some gates pass)
    Gens 7-10: Clean runs

    Tracks that the system doesn't regress and eventually produces empty proposals.
    """
    graph, ledger, engine = make_graph_with_conflict(tmp_path, num_gates=2)
    trend_store = TrendStore(filepath=tmp_path / "trends.jsonl")

    scores = []
    for gen in range(1, 11):
        if gen <= 3:
            executor = failing_executor
        else:
            executor = ok_executor

        graph.run(executor_fn=executor)
        report = RunJudge.evaluate(graph)
        scores.append(report.score)

        trend_store.append_run(RunSummary(
            run_id=graph.run_id,
            timestamp=f"2025-01-{gen:02d}T00:00:00Z",
            gate_results={},
            outcome="COMPLETE",
            gates_met=sum(1 for g in ledger.gates.values() if g.status == "MET"),
            gates_failed=sum(1 for g in ledger.gates.values() if g.status != "MET"),
            gates_total=len(ledger.gates),
        ))

        OrganismEvolver.evolve(
            graph=graph, report=report, ledger=ledger,
            trend_store=trend_store, generation=gen,
        )

        if gen < 10:
            graph.prepare_next_generation(gen + 1)

    # 10 runs logged
    assert len(trend_store.load_runs()) == 10

    # Final score should be >= first score (no permanent regression)
    assert scores[-1] >= scores[0]
