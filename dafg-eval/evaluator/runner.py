"""Evaluation runner orchestrating randomized trials across baseline, DAFG v0.1, and DAFG v0.2."""

import asyncio
import json
import os
import random
import shutil
import tempfile
import time
from pathlib import Path
from typing import Dict, List, Optional

from dafg_eval.benchmark.tasks import get_all_benchmark_tasks, BenchmarkTask
from dafg_eval.evaluator.external_judge import ExternalJudge
from dafg_eval.harnesses.harness_a import HarnessA
from dafg_eval.harnesses.harness_b import HarnessB

async def run_single_trial(
    task: BenchmarkTask,
    harness,
    mode: str,
    repetition: int,
    judge: ExternalJudge,
    results_dir: Path,
    ablation: Optional[str] = None
) -> tuple:
    # 1. Create fresh isolated ephemeral workspace
    with tempfile.TemporaryDirectory(prefix=f"eval_{task.id}_{mode}_") as temp_dir:
        workspace = Path(temp_dir)
        
        # Populate repository snapshot
        for rel_path, content in task.files.items():
            dest = workspace / rel_path
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(content)

        # 2. Run harness
        exec_res = await harness.run(
            task=task,
            workspace=workspace,
            mode=mode,
            token_limit=task.token_budget,
            timeout_sec=task.timeout_sec,
            ablation=ablation
        )

        # 3. Blinded External Evaluation
        eval_rep = judge.evaluate(task, workspace, exec_res)

        trial_data = {
            "task_id": task.id,
            "category": task.category,
            "title": task.title,
            "harness": harness.name,
            "mode": mode,
            "ablation": ablation or "none",
            "repetition": repetition,
            "status": exec_res.status,
            "outcome": eval_rep.outcome.value if hasattr(eval_rep.outcome, "value") else str(eval_rep.outcome),
            "verified_completion": eval_rep.verified_completion,
            "false_success": eval_rep.false_success,
            "honest_blocker_identified": eval_rep.honest_blocker_identified,
            "tokens_used": exec_res.tokens_used,
            "wall_clock_sec": exec_res.wall_clock_sec,
            "error": eval_rep.error_message,
        }

        return trial_data, exec_res.trace

async def run_full_suite(repetitions: int = 3, run_ablations: bool = True) -> Dict:
    tasks = get_all_benchmark_tasks()
    harness_a = HarnessA()
    harness_b = HarnessB()
    judge = ExternalJudge()

    results_dir = Path("dafg-eval/results")
    results_dir.mkdir(parents=True, exist_ok=True)

    trial_records = []
    traces = []

    # Build randomized trial schedule for 2x3 matrix (Baseline, v0.1, v0.2)
    schedule = []
    for rep in range(repetitions):
        for task in tasks:
            for harness in [harness_a, harness_b]:
                for mode in ["baseline", "dafg", "dafg_v0.2"]:
                    schedule.append((task, harness, mode, rep, None))

    if run_ablations:
        ablation_tasks = [t for t in tasks if t.category in ["multi_file_feature", "hidden_dependency", "fault_invalidation"]]
        ablations = ["baseline_prompted", "dafg_static_personas", "dafg_fixed_graph", "dafg_no_invalidation"]
        for rep in range(repetitions):
            for task in ablation_tasks:
                for ab in ablations:
                    mode = "baseline" if "baseline" in ab else "dafg"
                    schedule.append((task, harness_a, mode, rep, ab))

    random.shuffle(schedule)
    print(f"Executing {len(schedule)} randomized benchmark trials across Baseline, DAFG v0.1, and upgraded DAFG v0.2...")

    for idx, (task, harness, mode, rep, ab) in enumerate(schedule):
        trial, trace = await run_single_trial(task, harness, mode, rep, judge, results_dir, ab)
        trial_records.append(trial)
        traces.extend(trace)
        if (idx + 1) % 100 == 0 or (idx + 1) == len(schedule):
            print(f"  [{idx + 1}/{len(schedule)}] trials executed...")

    # Save raw records
    with open(results_dir / "raw_trials.jsonl", "w") as f:
        for r in trial_records:
            f.write(json.dumps(r) + "\n")

    with open(results_dir / "traces.jsonl", "w") as f:
        for t in traces:
            f.write(json.dumps(t) + "\n")

    print("Benchmark suite execution complete. Output written to dafg-eval/results/")
    return {"trials": trial_records, "total_trials": len(trial_records)}
