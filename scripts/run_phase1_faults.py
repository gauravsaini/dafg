"""Phase 1 calibrated fault matrix runner and defect-sensitivity reporter.

Loads 75 Phase 1 pilot tasks across four cohorts (multifile, protocol, concurrency,
impossible), executes the calibrated fault injection matrix across benchmark defect classes,
and persists the full audit report.

Stdlib-only implementation.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys

from dafg.eval import EvaluationHarness
from dafg.fault_matrix import FaultMatrixResult, run_calibrated_fault_matrix

__all__ = [
    "FaultMatrixResult",
    "run_calibrated_fault_matrix",
    "main",
]


def main() -> int:
    harness = EvaluationHarness()
    tasks = harness.load_phase1_pilot_tasks()
    assert len(tasks) == 75, f"expected 75 tasks, got {len(tasks)}"

    res: FaultMatrixResult = run_calibrated_fault_matrix(
        tasks,
        suite="phase1_faults",
        benchmark_revision="phase1-v1",
        command="uv run python scripts/run_phase1_faults.py",
    )

    out = Path("eval_results/phase1_fault_report.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(res.to_dict(), indent=2), encoding="utf-8")

    print(
        f"PHASE1_FAULTS: tasks={len(tasks)} trials={res['total_trials']} "
        f"detected={res['detected_faults']} classes={len(res['fault_classes'])}"
    )
    for cls_name, info in res["by_fault_class"].items():
        print(
            f"  {cls_name}: trials={info['total_trials']} "
            f"detected={info['detected']} rate={info['detection_rate']:.3f}"
        )
    print("PHASE1_FAULTS:OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
