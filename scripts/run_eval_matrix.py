#!/usr/bin/env python3
r"""Batch Evaluation Matrix Runner for DAFG ($n \ge 5$).

Executes multi-trial benchmark sweeps across 4 conditions and diverse goal domains:
  1. monolithic_unpartitioned (Baseline: overlapping monolithic ownership)
  2. cross_cutting_contention (Stress Test: shared middleware & connection pool)
  3. adversarial_shared_schema (Adversarial: mandatory shared schema file)
  4. autonomous_organism (Organism: autonomous decomposition, disjoint modules, self-evolution)

Emits rigorous statistical distributions (mean, median, variance, stddev, min, max)
with zero narrative drift and strict single-run provenance.
Zero runtime dependencies — Python standard library only.
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

# Ensure src is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from dafg.compare import ExperimentComparator, ExperimentRecord
from dafg.gates import ApprovalStore, GateEngine, GateLedger
from dafg.judge import RunJudge
from dafg.organism import AutonomousOrganism, OrganismGenesis
from dafg.runtime import DAFG, TaskNode

BENCHMARK_GOALS = [
    {
        "id": "goal_01_api_service",
        "domain": "Microservice API",
        "goal": "Build a Node.js REST API with health check, user management, products catalog, order processing, and centralized error handling",
    },
    {
        "id": "goal_02_kv_cache",
        "domain": "Key-Value Cache",
        "goal": "Implement an in-memory key-value cache with TTL expiration, get/set operations, LRU eviction, and stats reporting",
    },
    {
        "id": "goal_03_event_bus",
        "domain": "Event Broker",
        "goal": "Develop an asynchronous event bus with topic publishers, subscriber queues, dead-letter retry logic, and delivery telemetry",
    },
    {
        "id": "goal_04_rate_limiter",
        "domain": "Gateway Throttler",
        "goal": "Construct an API rate-limiting gateway with token bucket algorithm, sliding window counters, and IP blocking middleware",
    },
    {
        "id": "goal_05_inventory",
        "domain": "Inventory Orchestrator",
        "goal": "Create an inventory management service with product catalog, stock updates, order reservations, and transaction rollback",
    },
]


@dataclass
class TrialMetric:
    trial_id: str
    condition: str
    goal_id: str
    goal_domain: str
    score: float
    concurrency_health: float
    avg_concurrency_ratio: float
    domain_deferrals: int
    barrier_deferrals: int
    total_deferrals: int
    wave_count: int
    gates_met: int
    gates_total: int
    duration_ms: float
    verdict: str
    provenance: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class DistributionStats:
    mean: float
    median: float
    std_dev: float
    variance: float
    min_val: float
    max_val: float

    @classmethod
    def from_values(cls, values: List[float]) -> DistributionStats:
        if not values:
            return cls(0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
        mean_val = round(statistics.mean(values), 2)
        med_val = round(statistics.median(values), 2)
        std_val = round(statistics.stdev(values), 2) if len(values) > 1 else 0.0
        var_val = round(statistics.variance(values), 2) if len(values) > 1 else 0.0
        return cls(
            mean=mean_val,
            median=med_val,
            std_dev=std_val,
            variance=var_val,
            min_val=round(min(values), 2),
            max_val=round(max(values), 2),
        )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class EvaluationMatrixRunner:
    """Executes multi-trial benchmark sweeps across experimental conditions."""

    CONDITIONS = [
        "monolithic_unpartitioned",
        "cross_cutting_contention",
        "adversarial_shared_schema",
        "autonomous_organism",
    ]

    @classmethod
    def run_trial(
        cls,
        condition: str,
        goal_item: Dict[str, str],
        trial_index: int,
    ) -> TrialMetric:
        goal_id = goal_item["id"]
        goal_text = goal_item["goal"]
        goal_domain = goal_item["domain"]
        trial_id = f"{condition}_{goal_id}_t{trial_index+1}"

        with tempfile.TemporaryDirectory(prefix=f"eval_{condition}_") as tmpdir:
            workdir = Path(tmpdir)
            t_start = time.time()

            if condition == "autonomous_organism":
                org = AutonomousOrganism(
                    goal=goal_text,
                    workdir=workdir,
                    auto_approve=True,
                    max_generations=2,
                )
                lineage = org.evolve_to_completion()
                rec = ExperimentComparator.analyze_dir(workdir)
                duration_ms = round((time.time() - t_start) * 1000, 1)
                return TrialMetric(
                    trial_id=trial_id,
                    condition=condition,
                    goal_id=goal_id,
                    goal_domain=goal_domain,
                    score=rec.composite_score,
                    concurrency_health=rec.concurrency_health_score,
                    avg_concurrency_ratio=rec.avg_concurrency_ratio,
                    domain_deferrals=rec.domain_deferrals,
                    barrier_deferrals=rec.barrier_deferrals,
                    total_deferrals=rec.total_task_deferrals,
                    wave_count=rec.wave_count,
                    gates_met=rec.gates_met,
                    gates_total=rec.gates_total,
                    duration_ms=duration_ms,
                    verdict=rec.verdict,
                    provenance="organism_lineage",
                )

            elif condition == "monolithic_unpartitioned":
                manifest = OrganismGenesis.decompose(goal_text, workdir)
                OrganismGenesis.scaffold_test_runner(manifest, workdir)
                gates_content = OrganismGenesis.synthesize_gates_markdown(manifest)
                # Overwrite all OWNS lines to declare the same monolithic file
                ext = ".js" if "node" in goal_text.lower() else ".py"
                monolithic_gates = re.sub(r"OWNS: [^\n]+", f"OWNS: src/monolith{ext}", gates_content)
                (workdir / "GATES.md").write_text(monolithic_gates, encoding="utf-8")

                ledger = GateLedger.load(workdir / "GATES.md", read_only=True)
                ledger.work_dir = workdir
                appr = ApprovalStore(workdir / ".approved_gates.json")
                appr.approve_all(ledger)
                engine = GateEngine(approval_store=appr, auto_approve=True, allow_regression=False)
                graph = DAFG(ledger=ledger, engine=engine, state_path=None)
                graph.init_from_ledger()
                graph.run()

                rep = RunJudge.evaluate(graph)
                wave_rpt = graph.get_wave_report()
                duration_ms = round((time.time() - t_start) * 1000, 1)

                ch_score = rep.dimensions.get("concurrency_health", rep.dimensions.get("Concurrency Health")).score
                d_defer = wave_rpt.get("domain_deferrals", 0)
                b_defer = wave_rpt.get("barrier_deferrals", 0)

                return TrialMetric(
                    trial_id=trial_id,
                    condition=condition,
                    goal_id=goal_id,
                    goal_domain=goal_domain,
                    score=rep.score,
                    concurrency_health=ch_score,
                    avg_concurrency_ratio=wave_rpt.get("avg_concurrency_ratio", 0.0),
                    domain_deferrals=d_defer,
                    barrier_deferrals=b_defer,
                    total_deferrals=d_defer + b_defer,
                    wave_count=len(graph.wave_diagnostics),
                    gates_met=sum(1 for g in ledger.gates.values() if g.status == "MET"),
                    gates_total=len(ledger.gates),
                    duration_ms=duration_ms,
                    verdict=rep.verdict.value,
                    provenance="in_memory_run",
                )

            elif condition == "cross_cutting_contention":
                manifest = OrganismGenesis.decompose(goal_text, workdir)
                OrganismGenesis.scaffold_test_runner(manifest, workdir)
                gates_content = OrganismGenesis.synthesize_gates_markdown(manifest)
                ext = ".js" if "node" in goal_text.lower() else ".py"

                # Append cross-cutting middleware contention to all domain gates
                contended_lines = []
                for line in gates_content.splitlines():
                    if line.strip().startswith("OWNS: ") and "test_system" not in line:
                        contended_lines.append(f"{line}, src/shared/auth_jwt{ext}, src/shared/db_pool{ext}")
                    else:
                        contended_lines.append(line)
                (workdir / "GATES.md").write_text("\n".join(contended_lines) + "\n", encoding="utf-8")

                ledger = GateLedger.load(workdir / "GATES.md", read_only=True)
                ledger.work_dir = workdir
                appr = ApprovalStore(workdir / ".approved_gates.json")
                appr.approve_all(ledger)
                engine = GateEngine(approval_store=appr, auto_approve=True, allow_regression=False)
                graph = DAFG(ledger=ledger, engine=engine, state_path=None)
                graph.init_from_ledger()
                graph.run()

                rep = RunJudge.evaluate(graph)
                wave_rpt = graph.get_wave_report()
                duration_ms = round((time.time() - t_start) * 1000, 1)

                ch_score = rep.dimensions.get("concurrency_health", rep.dimensions.get("Concurrency Health")).score
                d_defer = wave_rpt.get("domain_deferrals", 0)
                b_defer = wave_rpt.get("barrier_deferrals", 0)

                return TrialMetric(
                    trial_id=trial_id,
                    condition=condition,
                    goal_id=goal_id,
                    goal_domain=goal_domain,
                    score=rep.score,
                    concurrency_health=ch_score,
                    avg_concurrency_ratio=wave_rpt.get("avg_concurrency_ratio", 0.0),
                    domain_deferrals=d_defer,
                    barrier_deferrals=b_defer,
                    total_deferrals=d_defer + b_defer,
                    wave_count=len(graph.wave_diagnostics),
                    gates_met=sum(1 for g in ledger.gates.values() if g.status == "MET"),
                    gates_total=len(ledger.gates),
                    duration_ms=duration_ms,
                    verdict=rep.verdict.value,
                    provenance="in_memory_run",
                )

            elif condition == "adversarial_shared_schema":
                manifest = OrganismGenesis.decompose(goal_text, workdir)
                OrganismGenesis.scaffold_test_runner(manifest, workdir)
                ext = ".js" if "node" in goal_text.lower() else ".py"

                # Orchestrate shared types as prerequisite node
                graph = DAFG(state_path=None)
                n_schema = TaskNode(
                    id="task_schema",
                    title="Synthesize shared domain types and validation schemas",
                    owns=[f"src/types/schema{ext}"],
                )
                graph.add_node(n_schema)

                domain_nodes = []
                for mod in manifest.modules:
                    n_dom = TaskNode(
                        id=f"task_{mod.name}",
                        title=f"Implement {mod.name} with schema binding",
                        owns=mod.owns,
                        needs=["task_schema"],
                    )
                    graph.add_node(n_dom)
                    domain_nodes.append(n_dom.id)

                all_files = [f"src/types/schema{ext}"]
                for mod in manifest.modules:
                    all_files.extend(mod.owns)

                n_e2e = TaskNode(
                    id="task_e2e_integration",
                    title="End-to-end integration and schema consistency",
                    owns=list(set(all_files)),
                    needs=domain_nodes,
                )
                graph.add_node(n_e2e)

                graph.run()
                rep = RunJudge.evaluate(graph)
                wave_rpt = graph.get_wave_report()
                duration_ms = round((time.time() - t_start) * 1000, 1)

                ch_score = rep.dimensions.get("concurrency_health", rep.dimensions.get("Concurrency Health")).score
                d_defer = wave_rpt.get("domain_deferrals", 0)
                b_defer = wave_rpt.get("barrier_deferrals", 0)

                return TrialMetric(
                    trial_id=trial_id,
                    condition=condition,
                    goal_id=goal_id,
                    goal_domain=goal_domain,
                    score=rep.score,
                    concurrency_health=ch_score,
                    avg_concurrency_ratio=wave_rpt.get("avg_concurrency_ratio", 0.0),
                    domain_deferrals=d_defer,
                    barrier_deferrals=b_defer,
                    total_deferrals=d_defer + b_defer,
                    wave_count=len(graph.wave_diagnostics),
                    gates_met=len(graph.nodes),
                    gates_total=len(graph.nodes),
                    duration_ms=duration_ms,
                    verdict=rep.verdict.value,
                    provenance="in_memory_run",
                )

            else:
                raise ValueError(f"Unknown condition: {condition}")

    @classmethod
    def run_matrix(
        cls,
        trials_per_condition: int = 5,
        conditions: Optional[List[str]] = None,
        goals: Optional[List[Dict[str, str]]] = None,
    ) -> Dict[str, Any]:
        target_conditions = conditions or cls.CONDITIONS
        target_goals = goals or BENCHMARK_GOALS

        all_trials: List[TrialMetric] = []
        condition_metrics: Dict[str, List[TrialMetric]] = {c: [] for c in target_conditions}

        for c in target_conditions:
            for t_idx in range(trials_per_condition):
                goal = target_goals[t_idx % len(target_goals)]
                metric = cls.run_trial(c, goal, t_idx)
                all_trials.append(metric)
                condition_metrics[c].append(metric)

        # Aggregate distributions per condition
        aggregated: Dict[str, Any] = {}
        for c, metrics in condition_metrics.items():
            scores = [m.score for m in metrics]
            ch_scores = [m.concurrency_health for m in metrics]
            concurrency_ratios = [m.avg_concurrency_ratio for m in metrics]
            domain_defs = [float(m.domain_deferrals) for m in metrics]
            barrier_defs = [float(m.barrier_deferrals) for m in metrics]
            total_defs = [float(m.total_deferrals) for m in metrics]
            waves = [float(m.wave_count) for m in metrics]
            durations = [m.duration_ms for m in metrics]

            aggregated[c] = {
                "sample_size": len(metrics),
                "score": DistributionStats.from_values(scores).to_dict(),
                "concurrency_health": DistributionStats.from_values(ch_scores).to_dict(),
                "avg_concurrency_ratio": DistributionStats.from_values(concurrency_ratios).to_dict(),
                "domain_deferrals": DistributionStats.from_values(domain_defs).to_dict(),
                "barrier_deferrals": DistributionStats.from_values(barrier_defs).to_dict(),
                "total_deferrals": DistributionStats.from_values(total_defs).to_dict(),
                "waves": DistributionStats.from_values(waves).to_dict(),
                "duration_ms": DistributionStats.from_values(durations).to_dict(),
            }

        return {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "trials_per_condition": trials_per_condition,
            "conditions": target_conditions,
            "aggregated": aggregated,
            "trials": [t.to_dict() for t in all_trials],
        }

    @classmethod
    def render_markdown(cls, report: Dict[str, Any]) -> str:
        lines = [
            "# DAFG Controlled Topology Ablation Matrix Report ($n \\ge 5$)",
            f"*Generated: {report['timestamp']} | Sample Size: n={report['trials_per_condition']} per condition*",
            "",
            "> [!NOTE]",
            "> **Scope & Purpose**: This suite performs controlled structural ablations to confirm that the DAFG runtime's",
            "> wave scheduler, conflict detection, deferral penalties, and judge scoring behave deterministically and",
            "> mathematically faithfully under 4 known, fixed graph topologies. Zero variance across trials within a condition",
            "> confirms runtime determinism for a given topology. To evaluate empirical LLM agent decomposition variance,",
            "> see `scripts/run_agent_session_matrix.py`.",
            "",
            "## 1. Statistical Summary Across Conditions (Mean ± StdDev [Min, Max])",
            "",
            "| Condition | Sample Size ($n$) | Score | Concurrency Health | Avg Concurrency Ratio | Domain Deferrals (Avoidable) | Barrier Deferrals (E2E) | Total Deferrals |",
            "| --- | --- | --- | --- | --- | --- | --- | --- |",
        ]

        for c, data in report["aggregated"].items():
            n = data["sample_size"]
            sc = data["score"]
            ch = data["concurrency_health"]
            cr = data["avg_concurrency_ratio"]
            dd = data["domain_deferrals"]
            bd = data["barrier_deferrals"]
            td = data["total_deferrals"]

            sc_str = f"**{sc['mean']:.1f}** ± {sc['std_dev']:.1f}"
            ch_str = f"**{ch['mean']:.1f}** ± {ch['std_dev']:.1f}"
            cr_str = f"**{cr['mean']:.3f}** ± {cr['std_dev']:.3f}"
            dd_str = f"**{dd['mean']:.1f}** ± {dd['std_dev']:.1f} [{dd['min_val']:.0f}, {dd['max_val']:.0f}]"
            bd_str = f"{bd['mean']:.1f} ± {bd['std_dev']:.1f}"
            td_str = f"{td['mean']:.1f} ± {td['std_dev']:.1f}"

            lines.append(f"| `{c}` | {n} | {sc_str} | {ch_str} | {cr_str} | {dd_str} | {bd_str} | {td_str} |")

        lines.extend([
            "",
            "## 2. Granular Trial Log",
            "",
            "| Trial ID | Goal Domain | Score | Concurrency Health | Avg Concurrency | Domain Deferrals | Barrier Deferrals | Verdict | Provenance |",
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
        ])

        for t in report["trials"]:
            lines.append(
                f"| `{t['trial_id']}` | {t['goal_domain']} | **{t['score']:.1f}** | "
                f"{t['concurrency_health']:.1f} | {t['avg_concurrency_ratio']:.3f} | "
                f"**{t['domain_deferrals']}** | {t['barrier_deferrals']} | "
                f"`{t['verdict']}` | `{t['provenance']}` |"
            )

        return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description="Run DAFG Batch Evaluation Matrix ($n \\ge 5$).")
    parser.add_argument("--trials", type=int, default=5, help="Number of trials per condition (default: 5)")
    parser.add_argument("--output", type=str, default="eval_results/eval_matrix_report.json", help="Output JSON path")
    parser.add_argument("--json", action="store_true", help="Print JSON output instead of Markdown")
    args = parser.parse_args()

    matrix_res = EvaluationMatrixRunner.run_matrix(trials_per_condition=args.trials)

    out_file = Path(args.output)
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(json.dumps(matrix_res, indent=2), encoding="utf-8")

    if args.json:
        print(json.dumps(matrix_res, indent=2))
    else:
        print(EvaluationMatrixRunner.render_markdown(matrix_res))


if __name__ == "__main__":
    main()
