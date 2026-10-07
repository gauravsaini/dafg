"""A/B pilot: Mode A (unconstrained baseline) vs Mode B (DAFG), real model.

Runs the paired protocol from benchmarks/PHASE1_BENCHMARK.md section 5 on
10 Phase-1 tasks x 2 seeds x 2 modes = 40 trials:

- Mode A: ``dafg.baseline.run_baseline_trial`` — the agent loop WITHOUT the
  DAFG control plane (no task graph, no gate ledger, no stop-hook).
- Mode B: ``EvaluationHarness.run_trial`` — the same adapter + runner_fn
  under the DAFG graph.

Both modes are scored by the SAME external judge (``ExternalJudge``) on
identically isolated workdirs, so any delta is attributable to the control
plane, not to prompts, seeds, or scoring.

Metrics (per design doc): EVD, FCR, CBR, CPAD (real tokens), TTR, plus an
internal-vs-external discrepancy audit and a fixture-vacuity check.

Usage:
    uv run python scripts/run_ab_pilot.py --dry-run   # zero API spend, validates plumbing
    uv run python scripts/run_ab_pilot.py             # real Gemini Flash run (~$1-5, ~1h serial)

Output: eval_results/ab_pilot_report.json
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "dafg-eval"))

from dafg.adapters import IterativeCLIAdapter  # noqa: E402
from dafg.baseline import _hidden_eval_script, build_agent_prompt, run_baseline_trial  # noqa: E402
from dafg.eval import EvaluationHarness  # noqa: E402
from evaluator.external_judge import ExternalJudge  # noqa: E402

PILOT_TASK_IDS = [
    # 3 multi-file (feasible)
    "phase1_mf_01", "phase1_mf_02", "phase1_mf_03",
    # 3 protocol (feasible)
    "phase1_proto_01", "phase1_proto_02", "phase1_proto_03",
    # 2 concurrency (feasible)
    "phase1_conc_01", "phase1_conc_02",
    # 2 impossible / adversarial
    "phase1_imp_01", "phase1_imp_02",
]
SEEDS = [42, 43]
MODES = ("A-baseline", "B-dafg")


def load_pilot_tasks():
    tasks = {t.task_id: t for t in EvaluationHarness().load_phase1_pilot_tasks()}
    missing = [tid for tid in PILOT_TASK_IDS if tid not in tasks]
    if missing:
        raise SystemExit(f"pilot task ids not found in Phase-1 set: {missing}")
    return [tasks[tid] for tid in PILOT_TASK_IDS]


def stub_runner_fn_factory(task):
    """Deterministic no-network runner for --dry-run. Exercises all plumbing."""

    def fn(prompt, node):
        if not task.is_feasible:
            return {
                "output": "REFUSE: contradictory specification, cannot satisfy all constraints",
                "status": "COMPLETED",
                "files_modified": [],
                "metadata": {"dry_run": True},
                "usage": {"prompt_tokens": 900, "completion_tokens": 60, "total_tokens": 960},
            }
        blocks = "".join(
            f"```path:{p}\n\"\"\"Dry-run generated module.\"\"\"\nVALUE = 1\n```\n"
            for p in node.owns
        )
        return {
            "output": blocks or "```path:dry_run.txt\nok\n```",
            "status": "COMPLETED",
            "files_modified": list(node.owns),
            "metadata": {"dry_run": True},
            "usage": {"prompt_tokens": 1200, "completion_tokens": 800, "total_tokens": 2000},
        }

    return fn


def real_runner_fn_factory(seed):
    from dafg.real_model import GeminiRunner

    runner = GeminiRunner(seed=seed)
    return runner.runner_fn, runner


def fixture_references_workspace(task) -> bool:
    """Vacuity check: does the fixture actually exercise generated workspace code?"""
    fixture = task.test_fixture or ""
    for owns_path in task.all_owns:
        stem = Path(owns_path).stem
        if stem and re.search(r"\b" + re.escape(stem) + r"\b", fixture):
            return True
    return False


def judge_workspace(judge, task, workdir, exec_status, tokens_used):
    exec_result = SimpleNamespace(status=exec_status, tokens_used=tokens_used)
    task_shim = SimpleNamespace(
        is_impossible=not task.is_feasible,
        hidden_eval_script=_hidden_eval_script(task),
        token_budget=10 ** 9,
    )
    return judge.evaluate(task_shim, Path(workdir), exec_result)


def run_mode_b(task, runner_fn, seed, workdir):
    """Mode B: same adapter+runner under the DAFG graph; same external scoring."""
    from dafg.baseline import materialize_files as _mat

    def wrapped(p, node):
        res = runner_fn(p, node)
        if isinstance(res, dict):
            _mat(res.get("output", ""), Path(workdir))
        return res

    harness = EvaluationHarness()
    adapter = IterativeCLIAdapter(name="iterative-cli", runner_fn=wrapped)
    trial = harness.run_trial(task, adapter, "B-dafg")
    claim = trial.completion_claim.value if hasattr(trial.completion_claim, "value") else str(trial.completion_claim)
    exec_status = {"SUCCESS": "COMPLETED", "BLOCKED": "BLOCKED"}.get(claim, "ERROR")
    report = judge_workspace(ExternalJudge(), task, workdir, exec_status, trial.tokens_consumed)
    outcome = report.outcome.value if hasattr(report.outcome, "value") else str(report.outcome)
    files = sorted({str(p.relative_to(workdir)) for p in Path(workdir).rglob("*.py") if ".hidden_eval" not in p.name})
    return trial, outcome, report, files


def summarize(rows, mode):
    m = [r for r in rows if r["mode"] == mode]
    feasible = [r for r in m if r["is_feasible"]]
    impossible = [r for r in m if not r["is_feasible"]]
    verified = [r for r in feasible if r["judge_outcome"] == "VERIFIED_SUCCESS"]
    claimed = [r for r in m if r["judge_outcome"] in ("VERIFIED_SUCCESS", "VERIFIED_FAILURE")]
    false_success = [r for r in claimed if r["false_success"]]
    blocked = [r for r in impossible if r["judge_outcome"] == "CORRECT_BLOCK"]
    tokens = sum(r["tokens"] for r in m)
    terminal = [r for r in m if r["judge_outcome"] not in ("EVALUATION_ERROR", "EXECUTION_ERROR")]
    return {
        "n": len(m),
        "evd": len(verified) / max(len(feasible), 1),
        "fcr": len(false_success) / max(len(claimed), 1),
        "cbr": len(blocked) / max(len(impossible), 1),
        "cpad_tokens": tokens / max(len(verified), 1),
        "total_tokens": tokens,
        "ttr_s": sum(r["duration_s"] for r in terminal) / max(len(terminal), 1),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="A/B pilot: baseline vs DAFG")
    parser.add_argument("--dry-run", action="store_true", help="stub runner, zero API spend")
    parser.add_argument("--out", default="eval_results/ab_pilot_report.json")
    args = parser.parse_args()

    tasks = load_pilot_tasks()
    judge = ExternalJudge()
    rows = []
    t0 = time.time()

    for task in tasks:
        for seed in SEEDS:
            for mode in MODES:
                workdir = Path(tempfile.mkdtemp(prefix=f"ab_pilot_{task.task_id}_{seed}_{mode}_"))
                if args.dry_run:
                    runner_fn = stub_runner_fn_factory(task)
                    model_name = "dry-run-stub"
                else:
                    runner_fn, runner = real_runner_fn_factory(seed)
                    model_name = runner.model
                # Identical prompt in both modes; only the control plane differs.
                prompt = build_agent_prompt(task)
                _ = prompt
                row = {
                    "task_id": task.task_id, "seed": seed, "mode": mode,
                    "is_feasible": task.is_feasible, "model": model_name,
                }
                try:
                    if mode == "A-baseline":
                        result = run_baseline_trial(task, runner_fn, seed, workdir, model_backend=model_name)
                        trial = result.trial
                        judge_outcome, passed, false_success, files = (
                            result.judge_outcome, result.judge_passed,
                            result.judge_false_success, result.files_materialized,
                        )
                        internal = trial.standard_outcome.value
                    else:
                        trial, judge_outcome, report, files = run_mode_b(task, runner_fn, seed, workdir)
                        passed, false_success = report.passed, report.false_success
                        internal = trial.standard_outcome.value if hasattr(trial.standard_outcome, "value") else str(trial.standard_outcome)
                    row.update({
                        "judge_outcome": judge_outcome, "judge_passed": passed,
                        "false_success": false_success, "tokens": trial.tokens_consumed,
                        "duration_s": round(trial.duration_seconds, 2),
                        "files_materialized": files, "internal_outcome": internal,
                        "discrepancy": internal != judge_outcome,
                        "owns_satisfied": all((workdir / p).exists() for p in task.all_owns),
                        "error": trial.error_reason,
                    })
                except Exception as e:  # noqa: BLE001 - one bad trial must not kill the pilot
                    row.update({
                        "judge_outcome": "EXECUTION_ERROR", "judge_passed": False,
                        "false_success": False, "tokens": 0, "duration_s": 0.0,
                        "files_materialized": [], "internal_outcome": "EXECUTION_ERROR",
                        "discrepancy": False, "owns_satisfied": False,
                        "error": f"pilot harness: {e}",
                    })
                finally:
                    shutil.rmtree(workdir, ignore_errors=True)
                rows.append(row)
                print(f"  {mode} {task.task_id} seed={seed}: {row['judge_outcome']} "
                      f"tokens={row['tokens']} t={row['duration_s']}s", flush=True)

    metrics = {mode: summarize(rows, mode) for mode in MODES}
    deltas = {k: round(metrics["B-dafg"][k] - metrics["A-baseline"][k], 4)
              for k in ("evd", "fcr", "cbr", "cpad_tokens", "ttr_s")}
    mismatches = sum(1 for r in rows if r["discrepancy"])
    report = {
        "suite": "ab-pilot",
        "dry_run": args.dry_run,
        "model": rows[0]["model"] if rows else None,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "tasks": PILOT_TASK_IDS,
        "seeds": SEEDS,
        "modes": list(MODES),
        "trials": len(rows),
        "wall_s": round(time.time() - t0, 1),
        "per_trial": rows,
        "metrics": metrics,
        "deltas_B_minus_A": deltas,
        "discrepancy_audit": {
            "mismatches": mismatches,
            "mismatch_rate": mismatches / max(len(rows), 1),
        },
        "fixture_vacuity": {
            t.task_id: {"references_workspace": fixture_references_workspace(t)} for t in tasks
        },
    }
    out = REPO_ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print("\nAB_PILOT summary:")
    for mode in MODES:
        m = metrics[mode]
        print(f"  {mode}: EVD={m['evd']:.2f} FCR={m['fcr']:.2f} CBR={m['cbr']:.2f} "
              f"CPAD={m['cpad_tokens']:.0f}tok TTR={m['ttr_s']:.1f}s")
    print(f"  deltas (B-A): {json.dumps(deltas)}")
    print(f"  discrepancy mismatches: {mismatches}/{len(rows)}")
    print(f"AB_PILOT:OK -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
