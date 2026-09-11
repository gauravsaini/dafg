"""Statistical analysis engine for DAFG evaluation using paired bootstrap resampling."""

import random
from typing import Dict, List, Tuple

def compute_metrics(trials: List[Dict]) -> Dict:
    total = len(trials)
    if total == 0:
        return {}

    verified = sum(1 for t in trials if t['verified_completion'])
    false_success = sum(1 for t in trials if t['false_success'])
    honest_blocks = sum(1 for t in trials if t.get('honest_blocker_identified', False))
    total_tokens = sum(t['tokens_used'] for t in trials)
    total_wall_sec = sum(t['wall_clock_sec'] for t in trials)

    verified_rate = verified / total
    false_success_rate = false_success / total
    cost_per_verified = (total_tokens / verified) if verified > 0 else float('inf')
    avg_latency = total_wall_sec / total

    outcomes = {
        "VERIFIED_SUCCESS": sum(1 for t in trials if t.get("outcome") == "VERIFIED_SUCCESS"),
        "VERIFIED_FAILURE": sum(1 for t in trials if t.get("outcome") == "VERIFIED_FAILURE"),
        "CORRECT_BLOCK": sum(1 for t in trials if t.get("outcome") == "CORRECT_BLOCK"),
        "EVALUATION_ERROR": sum(1 for t in trials if t.get("outcome") == "EVALUATION_ERROR"),
        "EXECUTION_ERROR": sum(1 for t in trials if t.get("outcome") == "EXECUTION_ERROR"),
    }

    return {
        'total_trials': total,
        'verified_count': verified,
        'verified_rate': verified_rate,
        'false_success_count': false_success,
        'false_success_rate': false_success_rate,
        'honest_blocks': honest_blocks,
        'outcomes': outcomes,
        'total_tokens': total_tokens,
        'cost_per_verified': cost_per_verified,
        'avg_latency_sec': avg_latency,
    }

def paired_bootstrap(
    trials_control: List[Dict],
    trials_treatment: List[Dict],
    metric_fn=lambda ts: sum(1 for t in ts if t['verified_completion']) / len(ts) if ts else 0,
    iterations: int = 10000,
    ci_level: float = 0.95
) -> Tuple[float, float, float]:
    """Performs paired bootstrap by task clustering to compute mean difference and 95% CI."""
    # Group trials by task_id
    by_task_c = {}
    for t in trials_control:
        by_task_c.setdefault(t['task_id'], []).append(t)

    by_task_t = {}
    for t in trials_treatment:
        by_task_t.setdefault(t['task_id'], []).append(t)

    task_ids = list(set(by_task_c.keys()) & set(by_task_t.keys()))
    if not task_ids:
        return 0.0, 0.0, 0.0

    diffs = []
    base_diff = metric_fn(trials_treatment) - metric_fn(trials_control)

    for _ in range(iterations):
        sample_tasks = [random.choice(task_ids) for _ in range(len(task_ids))]
        sample_c = [t for tid in sample_tasks for t in by_task_c[tid]]
        sample_t = [t for tid in sample_tasks for t in by_task_t[tid]]
        diff = metric_fn(sample_t) - metric_fn(sample_c)
        diffs.append(diff)

    diffs.sort()
    lower_idx = int((1 - ci_level) / 2 * iterations)
    upper_idx = int((1 + ci_level) / 2 * iterations)

    ci_lower = diffs[lower_idx]
    ci_upper = diffs[upper_idx]

    return base_diff, ci_lower, ci_upper
