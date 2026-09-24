"""Phase 1 verification-first comparison and telemetry summary module.

Evaluates benchmark trials by distinguishing self-reported agent completion claims
from verified outcomes (external judge success or correct refusal/blocking).
Stdlib-only implementation.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple, Union

from dafg.eval import CompletionClaim, StandardOutcome


def _normalize_claim(claim: Any) -> str:
    """Extract string value of completion claim."""
    if hasattr(claim, "value"):
        return str(claim.value)
    return str(claim) if claim is not None else ""


def _normalize_outcome(outcome: Any) -> str:
    """Extract string value of standard outcome."""
    if hasattr(outcome, "value"):
        return str(outcome.value)
    return str(outcome) if outcome is not None else ""


def _is_feasible(trial: Any) -> bool:
    """Extract task feasibility."""
    if hasattr(trial, "is_feasible"):
        return bool(trial.is_feasible)
    if isinstance(trial, dict):
        return bool(trial.get("is_feasible", True))
    return True


def _get_condition(trial: Any) -> str:
    """Extract trial condition or adapter."""
    if hasattr(trial, "condition") and trial.condition:
        return str(trial.condition)
    if hasattr(trial, "adapter") and trial.adapter:
        return str(trial.adapter)
    if isinstance(trial, dict):
        return str(trial.get("condition") or trial.get("adapter") or "default")
    return "default"


def _flatten_trials(trials_or_matrix: Any) -> Tuple[List[Any], Dict[str, List[Any]]]:
    """Normalize input into a flat list of trials and an arm/condition mapping."""
    flat: List[Any] = []
    by_arm: Dict[str, List[Any]] = {}

    if isinstance(trials_or_matrix, dict):
        if "trials" in trials_or_matrix and isinstance(trials_or_matrix["trials"], (list, tuple)):
            flat = list(trials_or_matrix["trials"])
            for t in flat:
                c = _get_condition(t)
                by_arm.setdefault(c, []).append(t)
        elif any(isinstance(v, (list, tuple)) for v in trials_or_matrix.values()):
            for arm_name, trial_list in trials_or_matrix.items():
                if isinstance(trial_list, (list, tuple)):
                    by_arm[arm_name] = list(trial_list)
                    flat.extend(trial_list)
                else:
                    by_arm.setdefault(arm_name, []).append(trial_list)
                    flat.append(trial_list)
        else:
            flat = list(trials_or_matrix.values())
            for t in flat:
                c = _get_condition(t)
                by_arm.setdefault(c, []).append(t)
    elif isinstance(trials_or_matrix, (list, tuple)):
        flat = list(trials_or_matrix)
        for t in flat:
            c = _get_condition(t)
            by_arm.setdefault(c, []).append(t)
    elif isinstance(trials_or_matrix, Iterable):
        flat = list(trials_or_matrix)
        for t in flat:
            c = _get_condition(t)
            by_arm.setdefault(c, []).append(t)
    elif trials_or_matrix is not None:
        flat = [trials_or_matrix]
        c = _get_condition(trials_or_matrix)
        by_arm.setdefault(c, []).append(trials_or_matrix)

    return flat, by_arm


def _calculate_metrics_for_trials(trials: List[Any]) -> Dict[str, Any]:
    """Compute core verification-first metrics for a list of trials."""
    total_trials = len(trials)
    feasible_trials = sum(1 for t in trials if _is_feasible(t))
    impossible_trials = total_trials - feasible_trials

    baseline_success_count = 0
    verified_success_count = 0
    correct_block_count = 0
    false_completion_count = 0

    for t in trials:
        claim_val = getattr(t, "completion_claim", None)
        if claim_val is None and isinstance(t, dict):
            claim_val = t.get("completion_claim")
        claim = _normalize_claim(claim_val)

        outcome_val = getattr(t, "standard_outcome", None)
        if outcome_val is None and isinstance(t, dict):
            outcome_val = t.get("standard_outcome")
        outcome = _normalize_outcome(outcome_val)

        # Baseline success: self-reported CompletionClaim.SUCCESS
        if claim == CompletionClaim.SUCCESS.value:
            baseline_success_count += 1
            if outcome != StandardOutcome.VERIFIED_SUCCESS.value:
                false_completion_count += 1

        # Verified outcomes: StandardOutcome.VERIFIED_SUCCESS or CORRECT_BLOCK
        if outcome == StandardOutcome.VERIFIED_SUCCESS.value:
            verified_success_count += 1
        elif outcome == StandardOutcome.CORRECT_BLOCK.value:
            correct_block_count += 1

    verified_outcomes_count = verified_success_count + correct_block_count

    baseline_success_rate = (baseline_success_count / total_trials) if total_trials > 0 else 0.0
    verified_outcome_rate = (verified_outcomes_count / total_trials) if total_trials > 0 else 0.0
    delivery_rate = (verified_success_count / feasible_trials) if feasible_trials > 0 else 0.0
    correct_block_rate = (correct_block_count / impossible_trials) if impossible_trials > 0 else 0.0
    false_completion_rate = (false_completion_count / total_trials) if total_trials > 0 else 0.0
    false_claim_rate = (false_completion_count / baseline_success_count) if baseline_success_count > 0 else 0.0

    return {
        "total_trials": total_trials,
        "feasible_trials": feasible_trials,
        "impossible_trials": impossible_trials,
        "baseline_success_count": baseline_success_count,
        "baseline_success_rate": baseline_success_rate,
        "verified_success_count": verified_success_count,
        "correct_block_count": correct_block_count,
        "verified_outcomes_count": verified_outcomes_count,
        "verified_outcome_rate": verified_outcome_rate,
        "delivery_rate": delivery_rate,
        "delivery_success_rate": delivery_rate,
        "correct_block_rate": correct_block_rate,
        "false_completion_count": false_completion_count,
        "false_completion_rate": false_completion_rate,
        "false_claim_rate": false_claim_rate,
    }


def summarize_comparison(
    trials_or_matrix: Any,
    oracle_pass_rates: Optional[Union[Dict[str, float], float]] = None,
    threshold: float = 10.0,
) -> Dict[str, Any]:
    """Summarize verification-first telemetry across trials or trial matrix.

    Args:
        trials_or_matrix: Sequence of EvaluationTrial objects or dict matrix.
        oracle_pass_rates: Optional reference pass rate (float or dict per metric/task).
        threshold: Permissible tolerance / divergence threshold (default 10.0).

    Returns:
        Summary dict containing counts, baseline success, verified outcome rates,
        delivery rate, correct block rate, false completion rate, and oracle checks.
    """
    flat_trials, by_arm = _flatten_trials(trials_or_matrix)
    summary = _calculate_metrics_for_trials(flat_trials)

    # Arm/condition breakdown
    by_condition: Dict[str, Dict[str, Any]] = {}
    for arm_name, arm_trials in by_arm.items():
        by_condition[arm_name] = _calculate_metrics_for_trials(arm_trials)
    summary["by_condition"] = by_condition

    # Oracle pass rates evaluation
    within_threshold: Optional[bool] = True
    oracle_diff: Optional[float] = None
    oracle_comparison: Optional[Dict[str, Any]] = None

    if oracle_pass_rates is not None:
        if isinstance(oracle_pass_rates, (int, float)):
            target = float(oracle_pass_rates)
            target_pct = target * 100.0 if target <= 1.0 else target
            actual_pct = summary["delivery_rate"] * 100.0
            oracle_diff = abs(actual_pct - target_pct)
            within_threshold = oracle_diff <= threshold
        elif isinstance(oracle_pass_rates, dict):
            oracle_comparison = {}
            all_within = True
            for k, val in oracle_pass_rates.items():
                if k in ("delivery", "delivery_rate", "delivery_success_rate"):
                    actual = summary["delivery_rate"]
                elif k in ("correct_block", "correct_block_rate"):
                    actual = summary["correct_block_rate"]
                elif k in ("verified", "verified_outcome_rate", "verified_outcomes"):
                    actual = summary["verified_outcome_rate"]
                elif k in ("baseline", "baseline_success_rate"):
                    actual = summary["baseline_success_rate"]
                elif k in ("false_completion", "false_completion_rate"):
                    actual = summary["false_completion_rate"]
                else:
                    actual = summary["delivery_rate"]

                t_val = float(val)
                t_pct = t_val * 100.0 if t_val <= 1.0 else t_val
                a_pct = actual * 100.0
                diff = abs(a_pct - t_pct)
                ok = diff <= threshold
                if not ok:
                    all_within = False
                oracle_comparison[k] = {
                    "actual_rate": actual,
                    "oracle_rate": t_val,
                    "diff_pct": diff,
                    "within_threshold": ok,
                }
            within_threshold = all_within
            if oracle_comparison:
                oracle_diff = max(item["diff_pct"] for item in oracle_comparison.values())

    # Divergence between baseline self-claim and verified outcome
    gap = summary["baseline_success_rate"] - summary["verified_outcome_rate"]
    gap_pct = gap * 100.0
    gap_exceeds_threshold = abs(gap_pct) > threshold

    summary.update({
        "threshold": threshold,
        "oracle_pass_rates": oracle_pass_rates,
        "oracle_diff": oracle_diff,
        "within_threshold": within_threshold,
        "oracle_comparison": oracle_comparison,
        "inflation_gap": gap,
        "gap_pct": gap_pct,
        "gap_exceeds_threshold": gap_exceeds_threshold,
    })

    return summary


def run_comparison(
    trials_or_matrix: Any,
    oracle_pass_rates: Optional[Union[Dict[str, float], float]] = None,
    threshold: float = 10.0,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Execute phase 1 verification-first comparison evaluation.

    Delegates directly to summarize_comparison.
    """
    return summarize_comparison(
        trials_or_matrix,
        oracle_pass_rates=oracle_pass_rates,
        threshold=threshold,
        **kwargs,
    )
