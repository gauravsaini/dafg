"""DAFG Analytics Judge & Run Quality Evaluator.

Downstream judge that evaluates raw signals, DOF events, wave diagnostics,
repair attempts, persona adaptations, and historical gate trends to compute
quantitative run quality scores, classify runs (PERFECT, IMPERFECT, FAILED),
isolate friction points with severity & impact indexes, and provide actionable
system elevation recommendations.

Zero runtime dependencies (stdlib only).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from dafg.gates import EvidenceStrength, classify_evidence


class QualityVerdict(str, Enum):
    """Overall quality grade for a DAFG execution run."""
    PERFECT = "PERFECT"      # score >= 85.0 and VERIFIED_DELIVERY
    IMPERFECT = "IMPERFECT"  # 50.0 <= score < 85.0
    HANDOFF_REQUIRED = "HANDOFF_REQUIRED"  # Deliberate refusal of automated signoff
    FAILED = "FAILED"        # score < 50.0 or non-delivery


class FrictionSeverity(str, Enum):
    """Standardized friction severity tiers."""
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


@dataclass
class QualityDimension:
    """Individual quality score component."""
    name: str
    score: float             # 0.0 - 100.0
    weight: float            # 0.0 - 1.0
    summary: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class FrictionPoint:
    """An isolated bottleneck, delay, or instability during execution.

    Carries severity tier (LOW/MEDIUM/HIGH), normalized numeric impact (0.0-1.0),
    and exact node/gate contextual bindings for future auto-tuning.
    """
    category: str            # SERIAL_CONFLICT, GATE_FAILURE, GATE_FLAKINESS, PERSONA_THRASH, REPAIR_THRASH, STALE_CASCADE, BUDGET_PRESSURE
    message: str
    severity: FrictionSeverity = FrictionSeverity.MEDIUM
    impact: float = 0.5      # 0.0 (negligible) to 1.0 (severe blocker)
    node_id: Optional[str] = None
    gate_id: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["severity"] = self.severity.value
        d["impact"] = round(self.impact, 3)
        return d


@dataclass
class RunQualityReport:
    """Comprehensive evaluative quality report for a DAFG run."""
    run_id: str
    verdict: QualityVerdict
    score: float
    outcome_status: str
    dimensions: Dict[str, QualityDimension]
    friction_points: List[FrictionPoint] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)
    friction_severity_index: float = 0.0  # Normalized aggregate friction impact (0.0 - 1.0)
    gate_flakiness_index: float = 0.0     # Historical gate instability ratio (0.0 - 1.0)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "verdict": self.verdict.value,
            "score": round(self.score, 1),
            "outcome_status": self.outcome_status,
            "friction_severity_index": round(self.friction_severity_index, 3),
            "gate_flakiness_index": round(self.gate_flakiness_index, 3),
            "dimensions": {k: v.to_dict() for k, v in self.dimensions.items()},
            "friction_points": [f.to_dict() for f in self.friction_points],
            "recommendations": self.recommendations,
        }

    def format_report(self) -> str:
        """Render a clean, human-readable terminal quality report."""
        lines = [
            "=" * 70,
            "                     DAFG RUN QUALITY REPORT",
            "=" * 70,
            f"  VERDICT:                 {self.verdict.value} (Score: {self.score:.1f}/100)",
            f"  DELIVERY STATE:          {self.outcome_status}",
            f"  FRICTION SEVERITY INDEX: {self.friction_severity_index:.2f} (0.0 = smooth, 1.0 = heavy drag)",
            f"  GATE FLAKINESS INDEX:    {self.gate_flakiness_index:.2f} (0.0 = stable, 1.0 = unstable)",
            "-" * 70,
            "  DIMENSIONAL SCORES:",
        ]
        for dim in self.dimensions.values():
            pct_bar = f"{dim.score:.1f}/100"
            lines.append(f"    • {dim.name:<25}: {pct_bar:>8} (weight: {int(dim.weight*100)}%) | {dim.summary}")

        lines.append("-" * 70)
        lines.append(f"  IDENTIFIED FRICTION POINTS ({len(self.friction_points)}):")
        if not self.friction_points:
            lines.append("    ✓ No friction detected. Clean execution flow.")
        else:
            for fp in self.friction_points:
                prefix = "[CRIT]" if fp.severity == FrictionSeverity.HIGH else ("[WARN]" if fp.severity == FrictionSeverity.MEDIUM else "[INFO]")
                ctx = f" (node={fp.node_id})" if fp.node_id else (f" (gate={fp.gate_id})" if fp.gate_id else "")
                lines.append(f"    {prefix:<6} [{fp.category}] (impact: {fp.impact:.2f}{ctx}) {fp.message}")

        lines.append("-" * 70)
        lines.append(f"  ELEVATION RECOMMENDATIONS ({len(self.recommendations)}):")
        if not self.recommendations:
            lines.append("    ✓ Architecture optimal. No elevation actions required.")
        else:
            for i, rec in enumerate(self.recommendations, 1):
                lines.append(f"    {i}. {rec}")

        lines.append("=" * 70)
        return "\n".join(lines)


class RunJudge:
    """Evaluates task graph execution across 6 quality dimensions and historical trends."""

    @classmethod
    def evaluate(
        cls,
        graph: Any,
        trend_store_path: Optional[Union[str, Path]] = None,
    ) -> RunQualityReport:
        """Judge a live or completed DAFG graph instance."""
        analytics = graph.get_run_analytics()
        return cls.evaluate_from_analytics(
            analytics,
            raw_graph=graph,
            trend_store_path=trend_store_path,
        )

    @classmethod
    def evaluate_from_analytics(
        cls,
        analytics: Dict[str, Any],
        raw_graph: Optional[Any] = None,
        trend_store_path: Optional[Union[str, Path]] = None,
    ) -> RunQualityReport:
        """Compute the RunQualityReport from analytics dict, graph snapshot, and trend history."""
        run_id = analytics.get("run_id", "unknown_run")
        funnel = analytics.get("funnel", {})
        concurrency = analytics.get("concurrency", {})
        budget_data = analytics.get("budget", {})
        gates = analytics.get("gates", {})
        outcome_status = funnel.get("outcome_status", "INCOMPLETE_RUN")
        is_sealed = funnel.get("is_sealed", False)

        friction_points: List[FrictionPoint] = []
        recommendations: List[str] = []

        # -------------------------------------------------------------------
        # 1. Convergence Discipline (weight: 25%)
        # -------------------------------------------------------------------
        total_nodes = funnel.get("total_nodes", 0)
        total_revisions = funnel.get("total_revisions", 0)
        revisions_ratio = (total_revisions / max(1, total_nodes)) if total_nodes > 0 else 0.0
        # 0 revisions = 100%, 1 rev/node = 50%, >=2 rev/node = 0%
        s_conv = max(0.0, min(100.0, (1.0 - (revisions_ratio / 2.0)) * 100.0))
        dim_conv = QualityDimension(
            name="Convergence Discipline",
            score=round(s_conv, 1),
            weight=0.25,
            summary=f"{total_revisions} revisions across {total_nodes} nodes ({revisions_ratio:.2f}/node)",
        )

        if revisions_ratio > 0.5:
            severity = FrictionSeverity.HIGH if revisions_ratio > 1.0 else FrictionSeverity.MEDIUM
            impact = min(1.0, revisions_ratio / 2.0)
            friction_points.append(FrictionPoint(
                category="REVISION_THRASH",
                message=f"High revision rate ({revisions_ratio:.2f} revisions/node) indicates specification ambiguity.",
                severity=severity,
                impact=impact,
            ))
            recommendations.append("Specify explicit InterfaceContract schemas to prevent iterative trial-and-error.")

        # -------------------------------------------------------------------
        # 2. Verification Integrity (weight: 25%)
        # -------------------------------------------------------------------
        gate_total = gates.get("total", 0)
        gate_met = gates.get("met", 0)
        pass_rate = gates.get("pass_rate", 0.0)

        if gate_total > 0:
            s_verif = pass_rate * 100.0
        else:
            accepted_nodes = funnel.get("accepted_nodes", 0)
            s_verif = (accepted_nodes / total_nodes * 100.0) if total_nodes > 0 else 100.0

        if gate_total > 0 and gate_met < gate_total:
            unmet = gate_total - gate_met
            impact = min(1.0, unmet / gate_total)
            friction_points.append(FrictionPoint(
                category="GATE_FAILURE",
                message=f"{unmet} of {gate_total} gate(s) failed or remain unverified.",
                severity=FrictionSeverity.HIGH,
                impact=impact,
            ))
            recommendations.append("Investigate failing gate CHECK commands and add pre-flight input manifests.")

        # Check evidence coverage
        cov_pct = gates.get("evidence_coverage")
        if cov_pct is None:
            cov_pct = gates.get("coverage_pct")
        if cov_pct is None and raw_graph is not None and getattr(raw_graph, "ledger", None):
            ledger = raw_graph.ledger
            t_g = len(ledger.gates)
            if t_g > 0:
                r_cnt = sum(
                    1 for g in ledger.gates.values()
                    if classify_evidence(g) in (EvidenceStrength.EXECUTABLE_PROOF, EvidenceStrength.STRING_MATCH)
                )
                cov_pct = round((r_cnt / t_g) * 100.0, 1)

        if gate_total > 0 and cov_pct is not None and cov_pct < 50.0:
            dock = round((50.0 - cov_pct) * 0.5, 1)
            s_verif = max(0.0, s_verif - dock)
            friction_points.append(FrictionPoint(
                category="LOW_EVIDENCE_COVERAGE",
                message=f"Low evidence coverage ({cov_pct:.1f}%): less than 50% of gates have runnable proof.",
                severity=FrictionSeverity.HIGH if cov_pct < 25.0 else FrictionSeverity.MEDIUM,
                impact=round(min(1.0, (50.0 - cov_pct) / 50.0), 2),
                details={"coverage_pct": cov_pct},
            ))
            recommendations.append("Replace subjective manual gates with executable CHECK and EXPECT verification commands.")


        # Check for unapproved check commands in audit log
        unapproved_deductions = 0
        if raw_graph is not None:
            for audit in getattr(raw_graph, "audit_log", []):
                reason = audit.get("reason", "").lower()
                if "unapproved" in reason or "security" in reason:
                    unapproved_deductions += 25
                    friction_points.append(FrictionPoint(
                        category="UNAPPROVED_COMMAND",
                        message=f"Unapproved gate command attempted: {audit.get('action')}",
                        severity=FrictionSeverity.HIGH,
                        impact=0.75,
                        node_id=audit.get("node_id"),
                    ))
                    recommendations.append("Pre-approve all command checks in .approved_gates.json prior to execution.")

        s_verif = max(0.0, min(100.0, s_verif - unapproved_deductions))
        dim_verif = QualityDimension(
            name="Verification Integrity",
            score=round(s_verif, 1),
            weight=0.25,
            summary=f"{gate_met}/{gate_total} gates met ({pass_rate*100:.1f}%)" if gate_total > 0 else "Node-backed verification",
        )

        # -------------------------------------------------------------------
        # 3. Concurrency Health (weight: 15%)
        # -------------------------------------------------------------------
        steps = concurrency.get("steps", 0)
        avg_cr = concurrency.get("avg_concurrency_ratio", 1.0)
        total_deferrals = concurrency.get("total_conflict_deferrals", 0)
        domain_deferrals = concurrency.get("domain_deferrals", total_deferrals)
        barrier_deferrals = concurrency.get("barrier_deferrals", 0)

        if steps <= 1:
            s_conc = 100.0
        else:
            s_conc = max(0.0, min(100.0, avg_cr * 100.0))

        # Only penalize avoidable domain-level conflict deferrals, not necessary terminal barrier waits!
        if domain_deferrals > 0:
            s_conc = max(10.0, s_conc - (domain_deferrals * 5.0))

        top_conflicts = concurrency.get("top_conflict_paths", [])
        if top_conflicts:
            for item in top_conflicts:
                if isinstance(item, (list, tuple)) and len(item) == 2:
                    p, cnt = item
                elif isinstance(item, dict):
                    p, cnt = item.get("path", "unknown"), item.get("count", 1)
                else:
                    p, cnt = str(item), 1
                impact = min(1.0, cnt * 0.25)
                severity = FrictionSeverity.HIGH if cnt >= 3 else FrictionSeverity.MEDIUM
                friction_points.append(FrictionPoint(
                    category="SERIAL_CONFLICT",
                    message=f"OWNS: conflict on '{p}' forced {cnt} task deferral(s) into serial waves.",
                    severity=severity,
                    impact=impact,
                    details={"path": p, "deferrals": cnt},
                ))
                recommendations.append(f"Split '{p}' ownership into finer subpaths or decouple via InterfaceContract.")
        elif domain_deferrals > 0:
            friction_points.append(FrictionPoint(
                category="SERIAL_CONFLICT",
                message=f"File ownership overlaps forced {domain_deferrals} task deferral(s).",
                severity=FrictionSeverity.MEDIUM,
                impact=min(1.0, domain_deferrals * 0.15),
                details={"deferrals": domain_deferrals},
            ))
            recommendations.append("Review node OWNS declarations to reduce shared file lock contention.")

        dim_conc = QualityDimension(
            name="Concurrency Health",
            score=round(s_conc, 1),
            weight=0.15,
            summary=f"Avg concurrency ratio: {avg_cr:.2f} (domain deferrals: {domain_deferrals}, barrier: {barrier_deferrals})",
        )

        # -------------------------------------------------------------------
        # 4. Resource Economy (weight: 15%)
        # -------------------------------------------------------------------
        calls_pct = budget_data.get("calls_pct", 0.0) / 100.0
        nodes_pct = budget_data.get("nodes_pct", 0.0) / 100.0
        max_burn = max(calls_pct, nodes_pct)
        s_econ = max(0.0, min(100.0, (1.0 - max_burn) * 100.0))
        dim_econ = QualityDimension(
            name="Resource Economy",
            score=round(s_econ, 1),
            weight=0.15,
            summary=f"Max burn: {max_burn*100:.1f}% (calls: {calls_pct*100:.1f}%, nodes: {nodes_pct*100:.1f}%)",
        )

        if max_burn > 0.80:
            severity = FrictionSeverity.HIGH if max_burn > 0.95 else FrictionSeverity.MEDIUM
            impact = round(max_burn, 2)
            friction_points.append(FrictionPoint(
                category="BUDGET_PRESSURE",
                message=f"Budget utilization reached {max_burn*100:.1f}%, risking run termination.",
                severity=severity,
                impact=impact,
            ))
            recommendations.append("Enable adaptive protocol bypass for single-file, low-ambiguity tasks to conserve budget.")

        # -------------------------------------------------------------------
        # 5. Persona Effectiveness Score (Dimension #5, weight: 10%)
        # -------------------------------------------------------------------
        persona_switches_total = 0
        persona_thrashing_count = 0
        spec_gap_deltas = []

        if raw_graph is not None:
            for node in getattr(raw_graph, "nodes", {}).values():
                p_history = node.metadata.get("persona_history", [])
                switches = len(p_history)
                if switches > 0:
                    persona_switches_total += switches
                if switches >= 2:
                    persona_thrashing_count += 1
                    friction_points.append(FrictionPoint(
                        category="PERSONA_THRASH",
                        message=f"Node '{node.id}' underwent {switches} persona switches due to capability mismatch.",
                        severity=FrictionSeverity.MEDIUM if switches == 2 else FrictionSeverity.HIGH,
                        impact=min(1.0, switches * 0.3),
                        node_id=node.id,
                    ))
                    recommendations.append(f"Pre-assign specialist capabilities on node '{node.id}' to eliminate persona drift.")

                # spec_gap_delta check
                if "spec_gap_delta" in node.metadata:
                    spec_gap_deltas.append(float(node.metadata["spec_gap_delta"]))

        if persona_switches_total == 0:
            s_persona = 100.0
            p_summary = "Zero persona drift; clean first-try specialization"
        else:
            # Penalize thrashing
            penalty = (persona_thrashing_count * 25.0) + (persona_switches_total * 10.0)
            s_persona = max(10.0, 100.0 - penalty)
            # Bonus if spec_gap_delta improved
            if spec_gap_deltas and (sum(spec_gap_deltas) / len(spec_gap_deltas)) > 0:
                s_persona = min(100.0, s_persona + 10.0)
            p_summary = f"{persona_switches_total} switches ({persona_thrashing_count} thrashing nodes)"

        dim_persona = QualityDimension(
            name="Persona Effectiveness",
            score=round(s_persona, 1),
            weight=0.10,
            summary=p_summary,
        )

        # -------------------------------------------------------------------
        # 6. Repair Stability Score (Dimension #6, weight: 10%)
        # -------------------------------------------------------------------
        repair_attempts_total = 0
        repair_failed_total = 0
        if raw_graph is not None:
            for node in getattr(raw_graph, "nodes", {}).values():
                r_results = node.metadata.get("repair_results", [])
                for rr in r_results:
                    attempts = rr.get("attempts", 1)
                    status = rr.get("final_status", "")
                    repair_attempts_total += attempts
                    if status not in ("REPAIRED", "MET"):
                        repair_failed_total += 1

                    if attempts >= 2:
                        friction_points.append(FrictionPoint(
                            category="REPAIR_THRASH",
                            message=f"Gate repair for node '{node.id}' required {attempts} cycles ({status}).",
                            severity=FrictionSeverity.HIGH if status != "REPAIRED" else FrictionSeverity.MEDIUM,
                            impact=min(1.0, attempts * 0.35),
                            node_id=node.id,
                        ))
                        recommendations.append(f"Increase repair diagnoser strictness and provide explicit fix directives on node '{node.id}'.")

        if repair_attempts_total == 0:
            s_repair = 100.0
            r_summary = "Zero repairs required; first-pass adequacy"
        else:
            penalty = (repair_failed_total * 40.0) + (repair_attempts_total * 15.0)
            s_repair = max(0.0, 100.0 - penalty)
            r_summary = f"{repair_attempts_total} repair attempt(s), {repair_failed_total} failed"

        dim_repair = QualityDimension(
            name="Repair Stability",
            score=round(s_repair, 1),
            weight=0.10,
            summary=r_summary,
        )

        # -------------------------------------------------------------------
        # 7. Stale Cascade Checks (from raw_graph)
        # -------------------------------------------------------------------
        if raw_graph is not None:
            current_epoch = getattr(raw_graph, "run_epoch", 1)
            stale_nodes = [n.id for n in getattr(raw_graph, "nodes", {}).values() if n.epoch < current_epoch]
            if stale_nodes:
                friction_points.append(FrictionPoint(
                    category="STALE_CASCADE",
                    message=f"Nodes {stale_nodes} were invalidated across multiple epochs.",
                    severity=FrictionSeverity.MEDIUM,
                    impact=min(1.0, len(stale_nodes) * 0.25),
                ))
                recommendations.append("Adopt backward-compatible InterfaceContract versions to prevent downstream invalidation cascades.")

        # -------------------------------------------------------------------
        # 8. Historical Gate Flakiness Index (TrendStore integration)
        # -------------------------------------------------------------------
        gate_flakiness_index = 0.0
        try:
            from dafg.trends import TrendAnalyzer, TrendStore
            trend_path = Path(trend_store_path) if trend_store_path else Path("eval_results/trends.jsonl")
            if trend_path.exists():
                store = TrendStore(filepath=trend_path)
                analyzer = TrendAnalyzer(store)
                flaky_gates = analyzer.get_flaky_gates()
                current_gate_ids = set()
                if raw_graph and getattr(raw_graph, "ledger", None):
                    current_gate_ids = set(raw_graph.ledger.gates.keys())

                flaky_in_run = [fg for fg in flaky_gates if fg.gate_id in current_gate_ids]
                if current_gate_ids:
                    gate_flakiness_index = round(len(flaky_in_run) / len(current_gate_ids), 3)

                for fg in flaky_in_run:
                    friction_points.append(FrictionPoint(
                        category="GATE_FLAKINESS",
                        message=f"Gate '{fg.gate_id}' has historical status flip rate ({fg.flip_count} flips, confidence {fg.confidence:.2f}).",
                        severity=FrictionSeverity.HIGH if fg.confidence < 0.5 else FrictionSeverity.MEDIUM,
                        impact=round(1.0 - fg.confidence, 3),
                        gate_id=fg.gate_id,
                        details={"flip_count": fg.flip_count, "confidence": fg.confidence},
                    ))
                    recommendations.append(f"Stabilize flaky gate '{fg.gate_id}' by isolating environmental dependencies or tightening determinism.")
        except Exception:
            pass  # Trend store analysis is best-effort

        # -------------------------------------------------------------------
        # Friction Severity Index Calculation
        # -------------------------------------------------------------------
        if friction_points:
            friction_severity_index = min(1.0, sum(fp.impact for fp in friction_points) / max(1, len(friction_points)))
        else:
            friction_severity_index = 0.0

        # -------------------------------------------------------------------
        # Composite Score & Verdict
        # -------------------------------------------------------------------
        dimensions = {
            "convergence_discipline": dim_conv,
            "verification_integrity": dim_verif,
            "concurrency_health": dim_conc,
            "resource_economy": dim_econ,
            "persona_effectiveness": dim_persona,
            "repair_stability": dim_repair,
        }

        composite = sum(d.score * d.weight for d in dimensions.values())

        # Delivery check: Must be delivered to be PERFECT or IMPERFECT
        delivered = outcome_status == "VERIFIED_DELIVERY" and (is_sealed or funnel.get("accepted_nodes", 0) == total_nodes)
        if outcome_status == "HANDOFF_REQUIRED":
            verdict = QualityVerdict.HANDOFF_REQUIRED
            composite = min(composite, 75.0)  # Capped below PERFECT (85.0)
        elif not delivered:
            verdict = QualityVerdict.FAILED
            composite = min(composite, 45.0)
        elif composite >= 85.0 and friction_severity_index < 0.20:
            verdict = QualityVerdict.PERFECT
        elif composite >= 50.0:
            verdict = QualityVerdict.IMPERFECT
        else:
            verdict = QualityVerdict.FAILED

        unique_recs = list(dict.fromkeys(recommendations))

        return RunQualityReport(
            run_id=run_id,
            verdict=verdict,
            score=round(composite, 1),
            outcome_status=outcome_status,
            dimensions=dimensions,
            friction_points=friction_points,
            recommendations=unique_recs,
            friction_severity_index=round(friction_severity_index, 3),
            gate_flakiness_index=round(gate_flakiness_index, 3),
        )
