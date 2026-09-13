#!/usr/bin/env python3
r"""Empirical Agent Session Matrix Runner for DAFG.

Analyzes and statistically aggregates real, empirical LLM agent sessions
against Autonomous Organism runs to measure actual behavioral variance
in file ownership, task deferrals, concurrency ratio, and composite scores.

Zero runtime dependencies — Python standard library only.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

# Ensure src is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from dafg.compare import ExperimentComparator, ExperimentRecord


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
        mean_val = round(statistics.mean(values), 3)
        med_val = round(statistics.median(values), 3)
        std_val = round(statistics.stdev(values), 3) if len(values) > 1 else 0.0
        var_val = round(statistics.variance(values), 3) if len(values) > 1 else 0.0
        return cls(
            mean=mean_val,
            median=med_val,
            std_dev=std_val,
            variance=var_val,
            min_val=round(min(values), 3),
            max_val=round(max(values), 3),
        )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class AgentSessionMatrix:
    """Statistical aggregator across empirical agent execution runs."""

    DEFAULT_LLM_DIRS = [
        "experiments/blackbox_goal_organism",
        "experiments/node_service_blackbox",
        "experiments/staged_scaling",
    ]

    DEFAULT_ORGANISM_DIRS = [
        "experiments/node_organism_eval",
        "experiments/redis_organism_eval",
    ]

    @classmethod
    def analyze_sessions(
        cls,
        llm_dirs: Optional[List[Path | str]] = None,
        organism_dirs: Optional[List[Path | str]] = None,
        fresh: bool = False,
    ) -> Dict[str, Any]:
        target_llm = [Path(p) for p in (llm_dirs or cls.DEFAULT_LLM_DIRS)]
        target_org = [Path(p) for p in (organism_dirs or cls.DEFAULT_ORGANISM_DIRS)]

        llm_records = [ExperimentComparator.analyze_dir(p, fresh=fresh) for p in target_llm if Path(p).exists()]
        org_records = [ExperimentComparator.analyze_dir(p, fresh=fresh) for p in target_org if Path(p).exists()]

        def _calc_group_stats(records: List[ExperimentRecord]) -> Dict[str, Any]:
            if not records:
                return {}
            cr = [r.avg_concurrency_ratio for r in records]
            dd = [float(r.domain_deferrals) for r in records]
            bd = [float(r.barrier_deferrals) for r in records]
            td = [float(r.total_task_deferrals) for r in records]
            ch = [r.concurrency_health_score for r in records]
            sc = [r.composite_score for r in records]
            ov = [float(len(r.overlapping_files)) for r in records]

            return {
                "sample_size": len(records),
                "avg_concurrency_ratio": DistributionStats.from_values(cr).to_dict(),
                "domain_deferrals": DistributionStats.from_values(dd).to_dict(),
                "barrier_deferrals": DistributionStats.from_values(bd).to_dict(),
                "total_deferrals": DistributionStats.from_values(td).to_dict(),
                "concurrency_health": DistributionStats.from_values(ch).to_dict(),
                "score": DistributionStats.from_values(sc).to_dict(),
                "overlapping_files_count": DistributionStats.from_values(ov).to_dict(),
            }

        return {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "groups": {
                "raw_llm_agent_sessions": _calc_group_stats(llm_records),
                "autonomous_organism_runs": _calc_group_stats(org_records),
            },
            "llm_trials": [r.to_dict() for r in llm_records],
            "organism_trials": [r.to_dict() for r in org_records],
        }

    @classmethod
    def render_markdown(cls, report: Dict[str, Any]) -> str:
        lines = [
            "# DAFG Empirical Agent Session Matrix Report",
            f"*Generated: {report['timestamp']}*",
            "",
            "> [!IMPORTANT]",
            "> **Empirical Agent Variance vs. Runtime Determinism**:",
            "> This report measures **real, empirical LLM agent sessions** across different goals and promptings,",
            "> capturing genuine stochastic variance in file ownership, task decomposition, and lock contention.",
            "",
            "## 1. Distribution Comparison: Raw LLM Sessions vs. Autonomous Organism",
            "",
            "| Cohort | Sample Size ($n$) | Score | Concurrency Health | Avg Concurrency Ratio | Domain Deferrals (Avoidable) | Barrier Deferrals (E2E) | Contended Files |",
            "| --- | --- | --- | --- | --- | --- | --- | --- |",
        ]

        for name, data in report["groups"].items():
            if not data:
                continue
            n = data["sample_size"]
            sc = data["score"]
            ch = data["concurrency_health"]
            cr = data["avg_concurrency_ratio"]
            dd = data["domain_deferrals"]
            bd = data["barrier_deferrals"]
            ov = data["overlapping_files_count"]

            sc_str = f"**{sc['mean']:.1f}** ± {sc['std_dev']:.1f}"
            ch_str = f"**{ch['mean']:.1f}** ± {ch['std_dev']:.1f}"
            cr_str = f"**{cr['mean']:.3f}** ± {cr['std_dev']:.3f}"
            dd_str = f"**{dd['mean']:.1f}** ± {dd['std_dev']:.1f} [{dd['min_val']:.0f}, {dd['max_val']:.0f}]"
            bd_str = f"{bd['mean']:.1f} ± {bd['std_dev']:.1f}"
            ov_str = f"{ov['mean']:.1f} ± {ov['std_dev']:.1f}"

            lines.append(f"| `{name}` | {n} | {sc_str} | {ch_str} | {cr_str} | {dd_str} | {bd_str} | {ov_str} |")

        lines.extend([
            "",
            "## 2. Granular Experiment Session Log",
            "",
            "| Session Directory | Cohort | Score | Concurrency Health | Avg Concurrency | Domain Deferrals | Barrier Deferrals | Total Deferrals | Verdict | Provenance |",
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
        ])

        for t in report["llm_trials"]:
            lines.append(
                f"| `{t['name']}` | `raw_llm_agent` | **{t['composite_score']:.1f}** | "
                f"{t['concurrency_health_score']:.1f} | {t['avg_concurrency_ratio']:.3f} | "
                f"**{t['domain_deferrals']}** | {t['barrier_deferrals']} | {t['total_task_deferrals']} | "
                f"`{t['verdict']}` | `{t['provenance']}` |"
            )

        for t in report["organism_trials"]:
            lines.append(
                f"| `{t['name']}` | `organism` | **{t['composite_score']:.1f}** | "
                f"{t['concurrency_health_score']:.1f} | {t['avg_concurrency_ratio']:.3f} | "
                f"**{t['domain_deferrals']}** | {t['barrier_deferrals']} | {t['total_task_deferrals']} | "
                f"`{t['verdict']}` | `{t['provenance']}` |"
            )

        return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description="Run DAFG Empirical Agent Session Matrix.")
    parser.add_argument("--llm-dirs", nargs="+", help="Paths to raw LLM agent experiment directories")
    parser.add_argument("--organism-dirs", nargs="+", help="Paths to organism experiment directories")
    parser.add_argument("--fresh", action="store_true", help="Re-evaluate directories in-memory without mutating on disk")
    parser.add_argument("--output", type=str, default="eval_results/agent_session_matrix_report.json", help="Output JSON path")
    parser.add_argument("--json", action="store_true", help="Print JSON output instead of Markdown")
    args = parser.parse_args()

    report = AgentSessionMatrix.analyze_sessions(
        llm_dirs=args.llm_dirs,
        organism_dirs=args.organism_dirs,
        fresh=args.fresh,
    )

    out_file = Path(args.output)
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(json.dumps(report, indent=2), encoding="utf-8")

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(AgentSessionMatrix.render_markdown(report))


if __name__ == "__main__":
    main()
