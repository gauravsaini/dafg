"""Execute the Phase 1 full matrix (75 tasks x 3 adapters x 1 seed) and record evidence.

Shakedown execution of the Phase 1 apparatus on stub adapters: proves the
matrix runs end-to-end with manifest provenance and discrepancy auditing.
Multi-seed statistical runs arrive with real model backends (seeds are
no-ops for deterministic stub adapters).
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from dafg.adapters import IterativeCLIAdapter, ReActStateAdapter, ToolDispatchAdapter
from dafg.eval import EvaluationHarness
from dafg.phase1 import run_phase1_matrix, summarize_matrix


def main() -> int:
    tasks = EvaluationHarness().load_phase1_pilot_tasks()
    assert len(tasks) == 75, f"expected 75 tasks, got {len(tasks)}"
    adapters = [IterativeCLIAdapter(), ToolDispatchAdapter(), ReActStateAdapter()]
    res = run_phase1_matrix(
        tasks,
        adapters,
        seeds=[42],
        suite="phase1",
        benchmark_revision="phase1-v1",
        command="uv run python scripts/run_phase1_matrix.py",
    )
    summary = summarize_matrix(res)
    report = {
        "suite": "phase1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "tasks": len(tasks),
        "seeds": [42],
        "modes": list(res.metrics.keys()),
        "trials": len(res.trials),
        "manifests": len(res.manifests),
        "metrics": {m: met.to_dict() for m, met in res.metrics.items()},
        "summary": dict(summary),
    }
    out = Path("eval_results/phase1_matrix_report.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"PHASE1_MATRIX: trials={len(res.trials)} modes={len(res.metrics)}")
    for m, met in res.metrics.items():
        d = met.to_dict()
        print(
            f"  {m}: delivery={d['delivery_success_rate']:.3f} "
            f"block={d['correct_block_rate']:.3f}"
        )
    print("PHASE1_MATRIX:OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
