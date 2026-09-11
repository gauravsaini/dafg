"""Main execution script for the DAFG Empirical Intervention Benchmark (v0.1 & upgraded v0.2)."""

import asyncio
import json
import os
import sys
from pathlib import Path

root_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root_dir / 'dafg-eval'))
sys.path.insert(0, str(root_dir))

from benchmark.tasks import get_all_benchmark_tasks
from evaluator.runner import run_full_suite
from analytics.stats import compute_metrics, paired_bootstrap

async def main():
    print("=========================================================================================")
    print("STARTING UPGRADED DAFG EMPIRICAL BENCHMARK (BASELINE vs DAFG v0.1 vs UPGRADED DAFG v0.2)")
    print("=========================================================================================")
    
    # 1. Execute full benchmark suite
    results = await run_full_suite(repetitions=3, run_ablations=True)
    trials = results["trials"]
    
    # 2. Slice into experimental conditions
    a0_trials = [t for t in trials if t['harness'] == 'HarnessA' and t['mode'] == 'baseline' and t['ablation'] == 'none']
    a1_trials = [t for t in trials if t['harness'] == 'HarnessA' and t['mode'] == 'dafg' and t['ablation'] == 'none']
    a2_trials = [t for t in trials if t['harness'] == 'HarnessA' and t['mode'] == 'dafg_v0.2' and t['ablation'] == 'none']

    b0_trials = [t for t in trials if t['harness'] == 'HarnessB' and t['mode'] == 'baseline' and t['ablation'] == 'none']
    b1_trials = [t for t in trials if t['harness'] == 'HarnessB' and t['mode'] == 'dafg' and t['ablation'] == 'none']
    b2_trials = [t for t in trials if t['harness'] == 'HarnessB' and t['mode'] == 'dafg_v0.2' and t['ablation'] == 'none']
    
    m_a0 = compute_metrics(a0_trials)
    m_a1 = compute_metrics(a1_trials)
    m_a2 = compute_metrics(a2_trials)

    m_b0 = compute_metrics(b0_trials)
    m_b1 = compute_metrics(b1_trials)
    m_b2 = compute_metrics(b2_trials)
    
    # 3. Bootstrap Statistical Significance
    delta_a1_a0, a1_low, a1_high = paired_bootstrap(a0_trials, a1_trials)
    delta_a2_a0, a2_low, a2_high = paired_bootstrap(a0_trials, a2_trials)
    delta_a2_a1, a21_low, a21_high = paired_bootstrap(a1_trials, a2_trials)

    delta_b1_b0, b1_low, b1_high = paired_bootstrap(b0_trials, b1_trials)
    delta_b2_b0, b2_low, b2_high = paired_bootstrap(b0_trials, b2_trials)
    delta_b2_b1, b21_low, b21_high = paired_bootstrap(b1_trials, b2_trials)
    
    # 4. Category breakdown
    categories = ["small_bug_fix", "multi_file_feature", "hidden_dependency", "interface_conflict", "fault_invalidation", "impossible_task"]
    cat_breakdown = {}
    for cat in categories:
        cat_breakdown[cat] = {
            'A0_Baseline': compute_metrics([t for t in a0_trials if t['category'] == cat]),
            'A1_DAFG_v0.1': compute_metrics([t for t in a1_trials if t['category'] == cat]),
            'A2_DAFG_v0.2': compute_metrics([t for t in a2_trials if t['category'] == cat]),
            'B0_Baseline': compute_metrics([t for t in b0_trials if t['category'] == cat]),
            'B1_DAFG_v0.1': compute_metrics([t for t in b1_trials if t['category'] == cat]),
            'B2_DAFG_v0.2': compute_metrics([t for t in b2_trials if t['category'] == cat]),
        }
        
    print("\n--- FACTORIAL OVERALL RESULTS (BASELINE vs v0.1 vs v0.2) ---")
    print(f"Condition A0 (Harness A Native):    Verified={m_a0['verified_rate']*100:.1f}%, FalseSuccess={m_a0['false_success_rate']*100:.1f}%, Cost/Verif={m_a0['cost_per_verified']:.0f} tokens")
    print(f"Condition A1 (Harness A + v0.1):   Verified={m_a1['verified_rate']*100:.1f}%, FalseSuccess={m_a1['false_success_rate']*100:.1f}%, Cost/Verif={m_a1['cost_per_verified']:.0f} tokens")
    print(f"Condition A2 (Harness A + v0.2):   Verified={m_a2['verified_rate']*100:.1f}%, FalseSuccess={m_a2['false_success_rate']*100:.1f}%, Cost/Verif={m_a2['cost_per_verified']:.0f} tokens")
    print(f"  -> Total Intervention Uplift (v0.2 vs Base): {delta_a2_a0*100:+.1f} pp [95% CI: {a2_low*100:+.1f}%, {a2_high*100:+.1f}%]")
    print(f"  -> Upgrade Uplift (v0.2 vs v0.1):            {delta_a2_a1*100:+.1f} pp [95% CI: {a21_low*100:+.1f}%, {a21_high*100:+.1f}%]")
    print("")
    print(f"Condition B0 (Harness B Native):    Verified={m_b0['verified_rate']*100:.1f}%, FalseSuccess={m_b0['false_success_rate']*100:.1f}%, Cost/Verif={m_b0['cost_per_verified']:.0f} tokens")
    print(f"Condition B1 (Harness B + v0.1):   Verified={m_b1['verified_rate']*100:.1f}%, FalseSuccess={m_b1['false_success_rate']*100:.1f}%, Cost/Verif={m_b1['cost_per_verified']:.0f} tokens")
    print(f"Condition B2 (Harness B + v0.2):   Verified={m_b2['verified_rate']*100:.1f}%, FalseSuccess={m_b2['false_success_rate']*100:.1f}%, Cost/Verif={m_b2['cost_per_verified']:.0f} tokens")
    print(f"  -> Total Intervention Uplift (v0.2 vs Base): {delta_b2_b0*100:+.1f} pp [95% CI: {b2_low*100:+.1f}%, {b2_high*100:+.1f}%]")
    print(f"  -> Upgrade Uplift (v0.2 vs v0.1):            {delta_b2_b1*100:+.1f} pp [95% CI: {b21_low*100:+.1f}%, {b21_high*100:+.1f}%]")
    
    summary_data = {
        "conditions": {"A0": m_a0, "A1": m_a1, "A2": m_a2, "B0": m_b0, "B1": m_b1, "B2": m_b2},
        "deltas": {
            "harness_a": {
                "v0.1_vs_baseline": {"mean": delta_a1_a0, "ci_95": [a1_low, a1_high]},
                "v0.2_vs_baseline": {"mean": delta_a2_a0, "ci_95": [a2_low, a2_high]},
                "v0.2_vs_v0.1": {"mean": delta_a2_a1, "ci_95": [a21_low, a21_high]}
            },
            "harness_b": {
                "v0.1_vs_baseline": {"mean": delta_b1_b0, "ci_95": [b1_low, b1_high]},
                "v0.2_vs_baseline": {"mean": delta_b2_b0, "ci_95": [b2_low, b2_high]},
                "v0.2_vs_v0.1": {"mean": delta_b2_b1, "ci_95": [b21_low, b21_high]}
            }
        },
        "category_breakdown": cat_breakdown
    }
    with open("dafg-eval/results/evaluation_summary_v0.2.json", "w") as f:
        json.dump(summary_data, f, indent=2)

    manifest_data = {
        "framework_version": "0.2.0-frozen",
        "commit": "2aae6b0",
        "evaluation_scope": "Synthetic 40-task benchmark suite",
        "harness_architecture": "One primary execution architecture (Harness A CLI Agent) with a secondary cost-modeling adapter (Harness B). Cross-runtime transfer untested.",
        "trial_accounting": {
            "total_trials_executed": len(trials),
            "tasks_count": 40,
            "repetitions_per_task": 3,
            "conditions_evaluated": ["A0", "A1", "A2", "B0", "B1", "B2"],
            "ablation_trials": len([t for t in trials if t['ablation'] != 'none'])
        },
        "evaluator_version": "v1.2.0-repaired-rubric",
        "outcome_taxonomy": [
            "VERIFIED_SUCCESS",
            "VERIFIED_FAILURE",
            "CORRECT_BLOCK",
            "EVALUATION_ERROR",
            "EXECUTION_ERROR"
        ],
        "bootstrap_parameters": {
            "iterations": 10000,
            "clustering": "task_id",
            "confidence_level": 0.95
        }
    }
    with open("dafg-eval/results/evaluation_manifest_v0.2.json", "w") as f:
        json.dump(manifest_data, f, indent=2)

    print("\nEvaluation summary saved to dafg-eval/results/evaluation_summary_v0.2.json")
    print("Evaluation manifest saved to dafg-eval/results/evaluation_manifest_v0.2.json")

if __name__ == '__main__':
    asyncio.run(main())
