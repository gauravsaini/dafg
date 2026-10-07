"""Run the DAFG graph-isolation A/B experiment.

Three modes (G-dafg-graph / S-sequential / P-naive-parallel) on three synthetic
shapes (fanout / conflict / runaway). Deterministic, zero API spend, no network.

Writes eval_results/graph_ab_report.json
"""

from __future__ import annotations

import json
import sys
import tempfile
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from dafg.graph_ab import REPS, MODES, build_report, run_trial  # noqa: E402


def main() -> int:
    t0 = time.time()
    results = []
    with tempfile.TemporaryDirectory(prefix="graph_ab_") as tmp:
        root = Path(tmp)
        for shape_id, reps in REPS.items():
            for mode in MODES:
                for rep in range(reps):
                    print(f"  {shape_id} x {mode} rep {rep}", flush=True)
                    results.append(run_trial(shape_id, mode, rep, root))
    report = build_report(results, time.time() - t0)
    out = REPO_ROOT / "eval_results" / "graph_ab_report.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print("\nGRAPH_AB summary:")
    for shape_id, sh in report["shapes"].items():
        m = sh["modes"]
        print(f"  {shape_id}:")
        for mode in MODES:
            d = m[mode]
            print(
                f"    {mode}: wall={d['wall_s_mean']}s waves={d['waves_used_mean']} "
                f"defer={d['deferrals_total']} corr_rate={d['corruption_rate']} "
                f"starved={d['starved_total']} hangs={d['hangs_total']}"
            )
        print(f"    verdict: {sh['verdict']}")
    print(f"GRAPH_AB:OK -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
