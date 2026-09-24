"""Phase 1 benchmark execution matrix and discrepancy summarization.

Runs evaluation suites across tasks x adapters x seeds via EvaluationHarness,
recording full manifest provenance and auditing delivery success, correct blocks,
and false completions against ground-truth oracle pass rates.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Union
import uuid

from dafg.adapters import BaseRuntimeAdapter
from dafg.eval import (
    BenchmarkTask,
    CompletionClaim,
    EvaluationHarness,
    EvaluationManifest,
    EvaluationMetrics,
    EvaluationTrial,
    StandardOutcome,
    _environment_digest,
    _source_commit,
)
from dafg.oracle import audit_discrepancy


def _get_source_commit() -> Optional[str]:
    """Retrieve source commit safely."""
    try:
        return _source_commit()
    except Exception:
        return None


def _get_environment_digest() -> str:
    """Retrieve stable interpreter environment digest safely."""
    try:
        return _environment_digest()
    except Exception:
        import platform

        facts = "\n".join((
            platform.python_implementation(),
            platform.python_version(),
            platform.platform(),
        ))
        return hashlib.sha256(facts.encode("utf-8")).hexdigest()


class TaskOutcomeList(list):
    """List of trial outcomes for a specific benchmark task with convenience helpers."""

    @property
    def standard_outcomes(self) -> List[StandardOutcome]:
        return [t.standard_outcome for t in self]

    @property
    def completion_claims(self) -> List[CompletionClaim]:
        return [t.completion_claim for t in self]

    @property
    def trials(self) -> List[EvaluationTrial]:
        return list(self)


class Phase1MatrixResult(dict):
    """Container for Phase 1 matrix execution results with dict and attribute access."""

    def __init__(
        self,
        metrics: Dict[str, EvaluationMetrics],
        outcomes: Dict[str, TaskOutcomeList],
        manifests: List[EvaluationManifest],
        trials: List[EvaluationTrial],
        harness: Optional[EvaluationHarness] = None,
        **kwargs: Any,
    ):
        super().__init__(
            metrics=metrics,
            per_mode_metrics=metrics,
            outcomes=outcomes,
            per_task_outcomes=outcomes,
            manifests=manifests,
            trials=trials,
            **kwargs,
        )
        self.metrics = metrics
        self.per_mode_metrics = metrics
        self.outcomes = outcomes
        self.per_task_outcomes = outcomes
        self.manifests = manifests
        self.trials = trials
        self.harness = harness


class Phase1Summary(dict):
    """Summary of Phase 1 matrix outcomes and oracle audit discrepancies."""

    def __init__(self, **kwargs: Any):
        super().__init__(**kwargs)
        for k, v in kwargs.items():
            setattr(self, k, v)


def _resolve_adapter(adapter_spec: Union[BaseRuntimeAdapter, type]) -> BaseRuntimeAdapter:
    """Instantiate adapter class if needed, or return instance."""
    if isinstance(adapter_spec, type) and issubclass(adapter_spec, BaseRuntimeAdapter):
        return adapter_spec()
    return adapter_spec


def run_phase1_matrix(
    tasks: Sequence[BenchmarkTask],
    adapters: Sequence[Union[BaseRuntimeAdapter, type]],
    seeds: Union[Sequence[int], int] = (42,),
    *,
    model_backend: Optional[str] = None,
    suite: str = "phase1",
    tier: str = "phase1",
    benchmark_revision: Optional[str] = None,
    oracle_revision: Optional[str] = None,
    command: Optional[str] = None,
) -> Phase1MatrixResult:
    """Run each task x adapter x seed via harness run_trial with manifest provenance.

    Args:
        tasks: Sequence of BenchmarkTask instances.
        adapters: Sequence of adapter classes or BaseRuntimeAdapter instances.
        seeds: Sequence of integer random seeds or single integer seed.
        model_backend: Provenance identifier for the underlying model backend.
        suite: Benchmark suite identifier (defaults to 'phase1').
        tier: Benchmark tier identifier (defaults to 'phase1').
        benchmark_revision: Optional benchmark commit or version tag.
        oracle_revision: Optional oracle reference version.
        command: Optional invoking command string.

    Returns:
        Phase1MatrixResult containing per-mode metrics, per-task outcomes,
        manifest provenance list, and all collected trials.
    """
    seed_list: List[int] = [seeds] if isinstance(seeds, int) else list(seeds)
    if not seed_list:
        seed_list = [42]

    all_trials: List[EvaluationTrial] = []
    manifests: List[EvaluationManifest] = []
    per_mode_metrics: Dict[str, EvaluationMetrics] = {}
    per_task_outcomes: Dict[str, TaskOutcomeList] = {
        task.task_id: TaskOutcomeList() for task in tasks
    }

    env_digest = _get_environment_digest()
    commit = _get_source_commit()

    harness = EvaluationHarness(
        tasks=list(tasks),
        benchmark_revision=benchmark_revision,
        command=command,
        model_backend=model_backend,
        seed=seed_list[0] if seed_list else None,
        oracle_revision=oracle_revision,
    )

    for seed in seed_list:
        harness.seed = seed
        for adapter_spec in adapters:
            adapter_instance = _resolve_adapter(adapter_spec)
            mode = getattr(adapter_instance, "name", adapter_instance.__class__.__name__)
            ts = datetime.now(timezone.utc).isoformat()

            run_id = hashlib.sha256(
                f"{suite}_{mode}_{seed}_{ts}_{uuid.uuid4().hex}".encode("utf-8")
            ).hexdigest()[:16]

            manifest = EvaluationManifest(
                run_id=run_id,
                source_commit=commit,
                suite=suite,
                tier=tier,
                adapter=mode,
                benchmark_revision=benchmark_revision,
                command=command,
                model_backend=model_backend,
                seed=seed,
                oracle_revision=oracle_revision,
                environment_digest=env_digest,
                timestamp=ts,
            )
            manifests.append(manifest)

            for task in tasks:
                trial = harness.run_trial(
                    task=task,
                    adapter=adapter_instance,
                    condition_name=mode,
                )
                setattr(trial, "manifest", manifest)
                setattr(trial, "seed", seed)
                all_trials.append(trial)
                if task.task_id not in per_task_outcomes:
                    per_task_outcomes[task.task_id] = TaskOutcomeList()
                per_task_outcomes[task.task_id].append(trial)

    modes: List[str] = []
    for adapter_spec in adapters:
        inst = _resolve_adapter(adapter_spec)
        mode_name = getattr(inst, "name", inst.__class__.__name__)
        if mode_name not in modes:
            modes.append(mode_name)

    for mode in modes:
        per_mode_metrics[mode] = harness.compute_metrics(condition=mode)

    return Phase1MatrixResult(
        metrics=per_mode_metrics,
        outcomes=per_task_outcomes,
        manifests=manifests,
        trials=all_trials,
        harness=harness,
    )


def _is_false_completion(trial: EvaluationTrial) -> bool:
    """Determine whether a trial is a false completion."""
    claimed_success = (
        trial.completion_claim == CompletionClaim.SUCCESS
        or trial.completion_claim == "SUCCESS"
    )
    if not trial.is_feasible:
        return claimed_success and trial.standard_outcome != StandardOutcome.CORRECT_BLOCK
    return claimed_success and trial.standard_outcome != StandardOutcome.VERIFIED_SUCCESS


def _resolve_oracle_score(
    oracle_pass_rates: Optional[Union[Dict[str, Any], float, int]],
    key: str,
    default: float,
) -> float:
    """Extract expected oracle pass rate for a given metric or condition."""
    if oracle_pass_rates is None:
        return default
    if isinstance(oracle_pass_rates, (int, float)):
        return float(oracle_pass_rates)
    if isinstance(oracle_pass_rates, dict):
        if key in oracle_pass_rates:
            val = oracle_pass_rates[key]
            return float(val.get("pass_rate", val) if isinstance(val, dict) else val)
        if "pass_rate" in oracle_pass_rates:
            return float(oracle_pass_rates["pass_rate"])
        if "score" in oracle_pass_rates:
            return float(oracle_pass_rates["score"])
    return default


def summarize_matrix(
    matrix_result: Optional[Union[Phase1MatrixResult, Dict[str, Any], List[EvaluationTrial]]] = None,
    oracle_pass_rates: Optional[Union[Dict[str, Any], float, int]] = None,
    *,
    threshold: float = 10.0,
    **kwargs: Any,
) -> Phase1Summary:
    """Compute delivery success, correct block, false completion vs oracle pass rates via audit_discrepancy.

    Args:
        matrix_result: Phase1MatrixResult or result dict or trial list.
        oracle_pass_rates: Ground-truth rates on the percent scale 0.0-100.0
            (scalar overall rate, or dict of metric/mode rates); fractions
            must be converted by the caller (compare.py convention: rate*100).
        threshold: Discrepancy flagging threshold in percentage points (default 10.0).

    Returns:
        Phase1Summary with rates and audit_discrepancy results.
    """
    trials: List[EvaluationTrial] = []
    if matrix_result is not None:
        if isinstance(matrix_result, Phase1MatrixResult) or isinstance(matrix_result, dict):
            if "trials" in matrix_result:
                trials = list(matrix_result["trials"])
            elif "outcomes" in matrix_result:
                for outcome_list in matrix_result["outcomes"].values():
                    trials.extend(outcome_list)
        elif isinstance(matrix_result, (list, tuple)):
            trials = list(matrix_result)
        elif hasattr(matrix_result, "trials"):
            trials = list(matrix_result.trials)
    elif "trials" in kwargs:
        trials = list(kwargs["trials"])

    feasible_trials = [t for t in trials if t.is_feasible]
    impossible_trials = [t for t in trials if not t.is_feasible]

    total_trials = len(trials)
    feasible_count = len(feasible_trials)
    impossible_count = len(impossible_trials)

    verified_success_count = sum(
        1 for t in feasible_trials if t.standard_outcome == StandardOutcome.VERIFIED_SUCCESS
    )
    correct_block_count = sum(
        1 for t in impossible_trials if t.standard_outcome == StandardOutcome.CORRECT_BLOCK
    )
    false_completion_count = sum(1 for t in trials if _is_false_completion(t))

    delivery_success_rate = (
        round((verified_success_count / feasible_count) * 100.0, 4)
        if feasible_count > 0
        else 0.0
    )
    correct_block_rate = (
        round((correct_block_count / impossible_count) * 100.0, 4)
        if impossible_count > 0
        else 0.0
    )
    false_completion_rate = (
        round((false_completion_count / total_trials) * 100.0, 4)
        if total_trials > 0
        else 0.0
    )

    if isinstance(oracle_pass_rates, (int, float)):
        # Scalar is an overall pass rate: it targets delivery/block rates, but a
        # false-completion target cannot be derived from it (honest target is 0.0).
        oracle_delivery = float(oracle_pass_rates)
        oracle_block = float(oracle_pass_rates)
        oracle_fc = 0.0
    else:
        oracle_delivery = _resolve_oracle_score(oracle_pass_rates, "delivery_success", default=100.0)
        oracle_block = _resolve_oracle_score(oracle_pass_rates, "correct_block", default=100.0)
        oracle_fc = _resolve_oracle_score(oracle_pass_rates, "false_completion", default=0.0)

    delivery_discrepancy = audit_discrepancy(
        internal_score=delivery_success_rate,
        gt_dict=oracle_delivery,
        threshold=threshold,
    )
    block_discrepancy = audit_discrepancy(
        internal_score=correct_block_rate,
        gt_dict=oracle_block,
        threshold=threshold,
    )
    fc_discrepancy = audit_discrepancy(
        internal_score=false_completion_rate,
        gt_dict=oracle_fc,
        threshold=threshold,
    )

    by_mode: Dict[str, Dict[str, Any]] = {}
    modes = sorted(list({getattr(t, "condition", getattr(t, "adapter", "unknown")) for t in trials}))
    for m in modes:
        mode_trials = [t for t in trials if getattr(t, "condition", getattr(t, "adapter", "")) == m]
        m_feasible = [t for t in mode_trials if t.is_feasible]
        m_impossible = [t for t in mode_trials if not t.is_feasible]
        m_vs = sum(1 for t in m_feasible if t.standard_outcome == StandardOutcome.VERIFIED_SUCCESS)
        m_cb = sum(1 for t in m_impossible if t.standard_outcome == StandardOutcome.CORRECT_BLOCK)
        m_fc = sum(1 for t in mode_trials if _is_false_completion(t))

        m_ds_rate = round((m_vs / len(m_feasible)) * 100.0, 4) if m_feasible else 0.0
        m_cb_rate = round((m_cb / len(m_impossible)) * 100.0, 4) if m_impossible else 0.0
        m_fc_rate = round((m_fc / len(mode_trials)) * 100.0, 4) if mode_trials else 0.0

        m_oracle_delivery = oracle_delivery
        if isinstance(oracle_pass_rates, dict) and m in oracle_pass_rates:
            m_oracle_delivery = _resolve_oracle_score(
                oracle_pass_rates[m], "delivery_success", default=oracle_delivery
            )

        m_delivery_disc = audit_discrepancy(m_ds_rate, m_oracle_delivery, threshold=threshold)
        m_block_disc = audit_discrepancy(m_cb_rate, oracle_block, threshold=threshold)
        m_fc_disc = audit_discrepancy(m_fc_rate, oracle_fc, threshold=threshold)

        by_mode[m] = {
            "total_trials": len(mode_trials),
            "feasible_trials": len(m_feasible),
            "impossible_trials": len(m_impossible),
            "verified_success_count": m_vs,
            "correct_block_count": m_cb,
            "false_completion_count": m_fc,
            "delivery_success": m_ds_rate,
            "delivery_success_rate": m_ds_rate,
            "correct_block": m_cb_rate,
            "correct_block_rate": m_cb_rate,
            "false_completion": m_fc_rate,
            "false_completion_rate": m_fc_rate,
            "discrepancy": m_delivery_disc,
            "discrepancies": {
                "delivery_success": m_delivery_disc,
                "correct_block": m_block_disc,
                "false_completion": m_fc_disc,
            },
        }

    return Phase1Summary(
        total_trials=total_trials,
        feasible_trials=feasible_count,
        impossible_trials=impossible_count,
        verified_success_count=verified_success_count,
        correct_block_count=correct_block_count,
        false_completion_count=false_completion_count,
        delivery_success=delivery_success_rate,
        delivery_success_rate=delivery_success_rate,
        correct_block=correct_block_rate,
        correct_block_rate=correct_block_rate,
        false_completion=false_completion_rate,
        false_completion_rate=false_completion_rate,
        discrepancy=delivery_discrepancy,
        discrepancies={
            "delivery_success": delivery_discrepancy,
            "correct_block": block_discrepancy,
            "false_completion": fc_discrepancy,
        },
        by_mode=by_mode,
    )
