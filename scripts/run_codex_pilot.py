"""Codex pilot: Mode A (unconstrained baseline) vs Mode B (DAFG), real model.

Same paired protocol as scripts/run_ab_pilot.py, but the model backend is
gpt-6-luna (max reasoning) on the Mac via CodexMacRunner instead of the
sandbox-blocked Gemini connector.

Runs 10 Phase-1 tasks x 2 modes x 1 seed = 20 trials:

- Mode A: ``dafg.baseline.run_baseline_trial`` — the agent loop WITHOUT the
  DAFG control plane.
- Mode B: ``EvaluationHarness.run_trial`` — the same adapter + runner_fn
  under the DAFG graph.

Both modes are scored by the SAME external judge on identically isolated
workdirs, so any delta is attributable to the control plane.

Prompt design: the adapter invokes runner_fn once per node, so each call
carries a per-node prompt (``dafg.codex_mac.build_node_prompt``) with the
fenced ```path:``` block + REFUSE: convention. Identical in both modes.

Mac load discipline: CodexMacRunner caps concurrent Mac codex calls at 2
via a process-wide semaphore (kernel tracks take priority); the pilot adds
at most 2 trial threads on top.

Metrics: EVD, FCR, CBR, CPAD (real tokens from --json usage), TTR, plus an
internal-vs-external discrepancy audit and the fixture-vacuity check.

Usage:
    uv run python scripts/run_codex_pilot.py --out eval_results/codex_pilot_report.json

Output: eval_results/codex_pilot_report.json (rewritten after every trial,
so a killed run still leaves partial results).
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import shutil
import sys
import tempfile
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "dafg-eval"))

from dafg.adapters import IterativeCLIAdapter  # noqa: E402
from dafg.baseline import (  # noqa: E402
    _hidden_eval_script,
    materialize_files,
    run_baseline_trial,
)
from dafg.codex_mac import CodexMacRunner, build_node_prompt  # noqa: E402
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
SEEDS = [42]
MODES = ("A-baseline", "B-dafg")
MAX_TRIAL_THREADS = 2


def load_pilot_tasks():
    tasks = {t.task_id: t for t in EvaluationHarness().load_phase1_pilot_tasks()}
    missing = [tid for tid in PILOT_TASK_IDS if tid not in tasks]
    if missing:
        raise SystemExit(f"pilot task ids not found in Phase-1 set: {missing}")
    return [tasks[tid] for tid in PILOT_TASK_IDS]


def codex_runner_fn_factory(task, runner):
    """Substitute the per-node codex prompt; the adapter's own prompt is a stub."""

    def fn(prompt, node):
        _ = prompt  # adapter passes "CLI session completed for ..." — not task content
        return runner.runner_fn(build_node_prompt(task, node), node)

    return fn


def fixture_references_workspace(task) -> bool:
    """Vacuity check: does the fixture actually exercise generated workspace code?"""
    import re

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

    def wrapped(p, node):
        res = runner_fn(p, node)
        if isinstance(res, dict):
            materialize_files(res.get("output", ""), Path(workdir))
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


def run_one_trial(task, seed, mode, runner, model_name):
    workdir = Path(tempfile.mkdtemp(prefix=f"codex_pilot_{task.task_id}_{seed}_{mode}_"))
    row = {
        "task_id": task.task_id, "seed": seed, "mode": mode,
        "is_feasible": task.is_feasible, "model": model_name,
        "backend": "mac-codex",
    }
    try:
        runner_fn = codex_runner_fn_factory(task, runner)
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
            "error": f"pilot harness: {e}\n{traceback.format_exc(limit=3)}",
        })
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    return row


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
    cpad = tokens / max(len(verified), 1) if tokens else None
    return {
        "n": len(m),
        "evd": round(len(verified) / max(len(feasible), 1), 4),
        "fcr": round(len(false_success) / max(len(claimed), 1), 4),
        "cbr": round(len(blocked) / max(len(impossible), 1), 4),
        "cpad_tokens": round(cpad, 1) if cpad is not None else None,
        "total_tokens": tokens,
        "ttr_s": round(sum(r["duration_s"] for r in terminal) / max(len(terminal), 1), 1),
    }


def write_report(out_path, rows, tasks, runner, model_name, t0, partial):
    metrics = {mode: summarize(rows, mode) for mode in MODES}
    deltas = {}
    for k in ("evd", "fcr", "cbr", "ttr_s"):
        a, b = metrics["A-baseline"][k], metrics["B-dafg"][k]
        deltas[k] = round(b - a, 4)
    if metrics["A-baseline"]["cpad_tokens"] is not None and metrics["B-dafg"]["cpad_tokens"] is not None:
        deltas["cpad_tokens"] = round(metrics["B-dafg"]["cpad_tokens"] - metrics["A-baseline"]["cpad_tokens"], 1)
    else:
        deltas["cpad_tokens"] = None
    mismatches = sum(1 for r in rows if r["discrepancy"])
    report = {
        "suite": "codex-pilot",
        "model": model_name,
        "backend": "mac-codex",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "tasks": PILOT_TASK_IDS,
        "seeds": SEEDS,
        "modes": list(MODES),
        "trials": len(rows),
        "trials_expected": len(PILOT_TASK_IDS) * len(SEEDS) * len(MODES),
        "partial": partial,
        "wall_s": round(time.time() - t0, 1),
        "per_trial": rows,
        "metrics": metrics,
        "deltas_B_minus_A": deltas,
        "discrepancy_audit": {
            "mismatches": mismatches,
            "mismatch_rate": round(mismatches / max(len(rows), 1), 4),
        },
        "fixture_vacuity": {
            t.task_id: {"references_workspace": fixture_references_workspace(t)} for t in tasks
        },
        "runner_stats": {
            "calls": runner.calls,
            "timeouts": runner.timeouts,
            "failures": runner.failures,
            "total_prompt_tokens": runner.total_prompt_tokens,
            "total_completion_tokens": runner.total_completion_tokens,
            "max_concurrent": runner.max_concurrent,
        },
        "limitations": [
            "Per-node prompts: the adapter invokes runner_fn once per node; each call carries only its own OWNS files. Multi-file interface coherence across nodes is not assisted.",
            "Fixture vacuity stands: 0/10 pilot fixtures reference workspace code, so EVD is unlikely to discriminate on feasible tasks regardless of model quality.",
            "Single seed; wall-clock includes Mac codex latency under shared load with kernel-debug tracks.",
            "CPAD is None when the --json stream carries no usage events.",
        ],
    }
    out = REPO_ROOT / out_path
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Codex pilot: baseline vs DAFG on Mac gpt-6-luna")
    parser.add_argument("--out", default="eval_results/codex_pilot_report.json")
    parser.add_argument("--threads", type=int, default=MAX_TRIAL_THREADS)
    args = parser.parse_args()

    tasks = load_pilot_tasks()
    runner = CodexMacRunner()
    model_name = runner.model
    combos = [(t, s, m) for t in tasks for s in SEEDS for m in MODES]
    rows: list = []
    t0 = time.time()
    print(f"CODEX_PILOT: {len(combos)} trials, model={model_name}, threads={args.threads}", flush=True)

    def do(combo):
        task, seed, mode = combo
        row = run_one_trial(task, seed, mode, runner, model_name)
        print(f"  {mode} {task.task_id} seed={seed}: {row['judge_outcome']} "
              f"tokens={row['tokens']} t={row['duration_s']}s", flush=True)
        return row

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.threads) as pool:
        future_map = {pool.submit(do, c): c for c in combos}
        try:
            for future in concurrent.futures.as_completed(future_map):
                rows.append(future.result())
                write_report(args.out, rows, tasks, runner, model_name, t0, partial=True)
        except KeyboardInterrupt:
            print("CODEX_PILOT: interrupted — writing partial report", flush=True)
            for f in future_map:
                f.cancel()

    report = write_report(args.out, rows, tasks, runner, model_name, t0,
                          partial=len(rows) < len(combos))
    print("\nCODEX_PILOT summary:")
    for mode in MODES:
        m = report["metrics"][mode]
        print(f"  {mode}: EVD={m['evd']:.2f} FCR={m['fcr']:.2f} CBR={m['cbr']:.2f} "
              f"CPAD={m['cpad_tokens']}tok TTR={m['ttr_s']:.1f}s")
    print(f"  deltas (B-A): {json.dumps(report['deltas_B_minus_A'])}")
    print(f"  runner: calls={runner.calls} timeouts={runner.timeouts} failures={runner.failures}")
    print(f"CODEX_PILOT:OK -> {REPO_ROOT / args.out} (partial={report['partial']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
