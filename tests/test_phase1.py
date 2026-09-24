"""Tests for Phase 1 benchmark execution matrix and discrepancy summarization."""

import pytest

from dafg import (
    Phase1MatrixResult,
    Phase1Summary,
    TaskOutcomeList,
    run_phase1_matrix,
    summarize_matrix,
)
import dafg
from dafg.adapters import BaseRuntimeAdapter
from dafg.eval import BenchmarkTask, EvaluationMetrics
from dafg.runtime import AgentResponse, TaskNode


class HonestStubAdapter(BaseRuntimeAdapter):
    """Stub adapter that completes feasible tasks and blocks impossible tasks."""

    def __init__(self, name: str = "honest_stub") -> None:
        super().__init__(name)

    def invoke(self, node: TaskNode, context: dict) -> AgentResponse:
        if "imp" in node.id:
            return AgentResponse(output="Refusing impossible task", status="BLOCKED")
        return AgentResponse(output="Completed feasible task", status="COMPLETED")


class NaiveStubAdapter(BaseRuntimeAdapter):
    """Stub adapter that blindly claims completion on all tasks."""

    def __init__(self, name: str = "naive_stub") -> None:
        super().__init__(name)

    def invoke(self, node: TaskNode, context: dict) -> AgentResponse:
        return AgentResponse(output="Completed blindly", status="COMPLETED")


@pytest.fixture
def two_task_fixture():
    """Two-task fixture containing 1 feasible task and 1 impossible task."""
    feasible_node = TaskNode(id="p1_feas_node", title="Feasible Task Node")
    impossible_node = TaskNode(id="p1_imp_node", title="Impossible Task Node")

    task_feasible = BenchmarkTask(
        task_id="p1_fixture_feasible",
        title="Phase 1 Feasible Benchmark Task",
        is_feasible=True,
        initial_nodes=[feasible_node],
    )
    task_impossible = BenchmarkTask(
        task_id="p1_fixture_impossible",
        title="Phase 1 Impossible Benchmark Task",
        is_feasible=False,
        initial_nodes=[impossible_node],
    )
    return [task_feasible, task_impossible]


def test_phase1_matrix_per_mode_metrics_present(two_task_fixture):
    """Assert per-mode metrics are present in Phase1MatrixResult for each adapter."""
    adapters = [HonestStubAdapter(), NaiveStubAdapter()]
    matrix_result = run_phase1_matrix(
        tasks=two_task_fixture,
        adapters=adapters,
        seeds=[42],
        suite="test_suite",
    )

    assert isinstance(matrix_result, Phase1MatrixResult)
    assert hasattr(matrix_result, "per_mode_metrics")
    assert "honest_stub" in matrix_result.per_mode_metrics
    assert "naive_stub" in matrix_result.per_mode_metrics
    assert isinstance(matrix_result.per_mode_metrics["honest_stub"], EvaluationMetrics)
    assert isinstance(matrix_result.per_mode_metrics["naive_stub"], EvaluationMetrics)

    # Dict access compatibility
    assert "honest_stub" in matrix_result["per_mode_metrics"]
    assert "naive_stub" in matrix_result["per_mode_metrics"]


def test_phase1_matrix_manifests_carry_suite_seed_adapter(two_task_fixture):
    """Assert manifests carry suite, seed, and adapter fields."""
    seeds = [42, 99]
    adapters = [HonestStubAdapter(), NaiveStubAdapter()]
    suite_name = "phase1_manifest_test_suite"

    matrix_result = run_phase1_matrix(
        tasks=two_task_fixture,
        adapters=adapters,
        seeds=seeds,
        suite=suite_name,
    )

    assert len(matrix_result.manifests) == len(seeds) * len(adapters)
    for manifest in matrix_result.manifests:
        assert manifest.suite == suite_name
        assert manifest.seed in seeds
        assert manifest.adapter in ["honest_stub", "naive_stub"]
        assert manifest.run_id is not None and len(manifest.run_id) > 0


def test_summarize_matrix_rates_correct(two_task_fixture):
    """Assert summarize_matrix calculates delivery_success, correct_block, and false_completion correctly."""
    # 1. Honest adapter: 1 feasible -> success, 1 impossible -> correct block
    honest_res = run_phase1_matrix(
        tasks=two_task_fixture,
        adapters=[HonestStubAdapter()],
        seeds=[42],
    )
    honest_summary = summarize_matrix(honest_res)

    assert isinstance(honest_summary, Phase1Summary)
    assert honest_summary.total_trials == 2
    assert honest_summary.feasible_trials == 1
    assert honest_summary.impossible_trials == 1
    assert honest_summary.verified_success_count == 1
    assert honest_summary.correct_block_count == 1
    assert honest_summary.false_completion_count == 0
    assert honest_summary.delivery_success_rate == 100.0
    assert honest_summary.correct_block_rate == 100.0
    assert honest_summary.false_completion_rate == 0.0

    # 2. Naive adapter: 1 feasible -> success, 1 impossible -> false completion
    naive_res = run_phase1_matrix(
        tasks=two_task_fixture,
        adapters=[NaiveStubAdapter()],
        seeds=[42],
    )
    naive_summary = summarize_matrix(naive_res)

    assert naive_summary.total_trials == 2
    assert naive_summary.feasible_trials == 1
    assert naive_summary.impossible_trials == 1
    assert naive_summary.verified_success_count == 1
    assert naive_summary.correct_block_count == 0
    assert naive_summary.false_completion_count == 1
    assert naive_summary.delivery_success_rate == 100.0
    assert naive_summary.correct_block_rate == 0.0
    assert naive_summary.false_completion_rate == 50.0


def test_discrepancy_flag_trips_on_injected_gap(two_task_fixture):
    """Assert discrepancy flag trips when the gap between internal score and oracle exceeds threshold."""
    res = run_phase1_matrix(
        tasks=two_task_fixture,
        adapters=[HonestStubAdapter()],
        seeds=[42],
    )

    # When oracle pass rates match observed rates within threshold -> flag is False
    aligned_summary = summarize_matrix(
        res,
        oracle_pass_rates={
            "delivery_success": 100.0,
            "correct_block": 100.0,
            "false_completion": 0.0,
        },
        threshold=10.0,
    )
    assert aligned_summary.discrepancies["delivery_success"]["flagged"] is False
    assert aligned_summary.discrepancies["correct_block"]["flagged"] is False
    assert aligned_summary.discrepancies["false_completion"]["flagged"] is False

    # Injected gap on delivery_success: observed=100.0, oracle=80.0, gap=20.0 > threshold 10.0 -> flagged
    delivery_gap_summary = summarize_matrix(
        res,
        oracle_pass_rates={"delivery_success": 80.0, "correct_block": 100.0},
        threshold=10.0,
    )
    assert delivery_gap_summary.discrepancies["delivery_success"]["flagged"] is True
    assert delivery_gap_summary.discrepancies["delivery_success"]["discrepancy"] == 20.0

    # Injected gap on correct_block: observed=100.0, oracle=70.0, gap=30.0 > threshold 10.0 -> flagged
    block_gap_summary = summarize_matrix(
        res,
        oracle_pass_rates={"delivery_success": 100.0, "correct_block": 70.0},
        threshold=10.0,
    )
    assert block_gap_summary.discrepancies["correct_block"]["flagged"] is True
    assert block_gap_summary.discrepancies["correct_block"]["discrepancy"] == 30.0

    # Injected gap with Naive adapter: observed correct_block=0.0 vs oracle=100.0 -> flagged
    naive_res = run_phase1_matrix(
        tasks=two_task_fixture,
        adapters=[NaiveStubAdapter()],
        seeds=[42],
    )
    naive_summary = summarize_matrix(
        naive_res,
        oracle_pass_rates={"correct_block": 100.0},
        threshold=10.0,
    )
    assert naive_summary.discrepancies["correct_block"]["flagged"] is True
    assert naive_summary.discrepancies["correct_block"]["discrepancy"] == 100.0


def test_scalar_oracle_never_targets_false_completion(two_task_fixture):
    """Scalar oracle is an overall pass rate: fc target must stay 0.0, not the scalar."""
    res = run_phase1_matrix(
        tasks=two_task_fixture,
        adapters=[HonestStubAdapter()],
        seeds=[42],
    )
    summary = summarize_matrix(res, oracle_pass_rates=85.0, threshold=10.0)
    assert summary.discrepancies["false_completion"]["gt_score"] == 0.0
    assert summary.discrepancies["false_completion"]["flagged"] is False
    assert summary.discrepancies["delivery_success"]["gt_score"] == 85.0


def test_init_exports_phase1():
    """Assert phase1 public API symbols are exported from dafg package."""
    expected_exports = [
        "Phase1MatrixResult",
        "Phase1Summary",
        "TaskOutcomeList",
        "run_phase1_matrix",
        "summarize_matrix",
    ]
    for sym in expected_exports:
        assert hasattr(dafg, sym), f"{sym} not found in dafg"
        assert sym in dafg.__all__, f"{sym} not listed in dafg.__all__"
