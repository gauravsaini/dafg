"""Tests for batch evaluation matrix runner and statistical distribution reporting."""
from pathlib import Path
import json
import pytest

from scripts.run_eval_matrix import (
    EvaluationMatrixRunner,
    DistributionStats,
    BENCHMARK_GOALS,
)


def test_distribution_stats_computation():
    vals = [10.0, 20.0, 30.0, 40.0, 50.0]
    stats = DistributionStats.from_values(vals)
    assert stats.mean == 30.0
    assert stats.median == 30.0
    assert stats.min_val == 10.0
    assert stats.max_val == 50.0
    assert stats.std_dev == 15.81
    assert stats.variance == 250.0


def test_distribution_stats_empty():
    stats = DistributionStats.from_values([])
    assert stats.mean == 0.0
    assert stats.std_dev == 0.0


def test_matrix_runner_single_trial():
    goal = BENCHMARK_GOALS[0]
    metric = EvaluationMatrixRunner.run_trial("monolithic_unpartitioned", goal, 0)
    assert metric.condition == "monolithic_unpartitioned"
    assert metric.domain_deferrals == 15
    assert metric.concurrency_health == 10.0
    assert metric.score == 82.0

    metric_org = EvaluationMatrixRunner.run_trial("autonomous_organism", goal, 0)
    assert metric_org.condition == "autonomous_organism"
    assert metric_org.domain_deferrals == 0
    assert metric_org.score >= 85.0


def test_matrix_runner_render_markdown():
    res = EvaluationMatrixRunner.run_matrix(
        trials_per_condition=1,
        conditions=["monolithic_unpartitioned", "autonomous_organism"],
    )
    md = EvaluationMatrixRunner.render_markdown(res)
    assert "# DAFG Controlled Topology Ablation Matrix Report" in md
    assert "| `monolithic_unpartitioned` |" in md
    assert "| `autonomous_organism` |" in md
