"""Tests for DAFG v0.3 Evaluation Engine & Decoupled Adapters."""

import pytest
from dafg import (
    BenchmarkTask,
    CompletionClaim,
    EvaluationHarness,
    EvaluationMetrics,
    EvaluationTrial,
    IterativeCLIAdapter,
    NodeStatus,
    ReActStateAdapter,
    StandardOutcome,
    TaskNode,
    ToolDispatchAdapter,
    validate_test_fixture_syntax,
)


def test_test_fixture_syntax_validator():
    """Verify pre-flight validation catches fixture syntax errors before evaluation."""
    # 1. Valid fixture
    valid_code = "import json\ndata = {'name': 'Alice'}\nassert data['name'] == 'Alice'"
    ok, err = validate_test_fixture_syntax(valid_code)
    assert ok is True
    assert err is None

    # 2. Defective fixture (unterminated string literal as identified in cat2_feat_04)
    broken_code = "csv_data = 'name,age,email\nunclosed string"
    ok, err = validate_test_fixture_syntax(broken_code)
    assert ok is False
    assert "SyntaxError" in err


def test_evaluation_harness_catches_evaluation_error():
    """Defective test fixture must be categorized as EVALUATION_ERROR, not agent failure."""
    harness = EvaluationHarness()
    task = BenchmarkTask(
        task_id="test_broken_fixture",
        title="Task with broken fixture",
        test_fixture="def bad(syntax: return",
    )
    adapter = IterativeCLIAdapter()
    trial = harness.run_trial(task, adapter=adapter, condition_name="cli")

    assert trial.standard_outcome == StandardOutcome.EVALUATION_ERROR
    assert "SyntaxError" in trial.error_reason


def test_metrics_computation_with_claims():
    """Verify correct-outcome rate, delivery success, and correct blocking calculations."""
    metrics = EvaluationMetrics(
        total_trials=10,
        feasible_trials=8,
        impossible_trials=2,
        verified_success_count=7,
        correct_block_count=2,
        verified_failure_count=1,
        total_tokens=50000,
        feasible_tokens=40000,
    )

    # Correct outcomes = 7 + 2 = 9 out of 10 = 90.0%
    assert metrics.correct_outcome_rate == 0.90
    # Delivery success = 7 out of 8 = 87.5%
    assert metrics.delivery_success_rate == 0.875
    # Correct blocking = 2 out of 2 = 100.0%
    assert metrics.correct_block_rate == 1.0
    # Tokens per correct outcome = 50000 / 9 = 5555.55
    assert round(metrics.tokens_per_correct_outcome, 1) == 5555.6
    # Tokens per delivery = 40000 / 7 = 5714.28
    assert round(metrics.tokens_per_delivery, 1) == 5714.3


def test_decoupled_adapters():
    """Verify all three decoupled agent adapters produce valid responses."""
    node = TaskNode(id="t_mod", title="Build module", owns=["src/mod.py"])
    ctx = {}

    # 1. Iterative CLI Adapter
    cli = IterativeCLIAdapter()
    resp_cli = cli.invoke(node, ctx)
    assert resp_cli.status == "COMPLETED"
    assert "src/mod.py" in resp_cli.files_modified
    assert cli.total_tokens_consumed > 0

    # 2. Tool Dispatch Adapter
    dispatch = ToolDispatchAdapter()
    resp_disp = dispatch.invoke(node, ctx)
    assert resp_disp.status == "COMPLETED"
    assert len(dispatch.dispatched_tool_calls) == 1
    assert dispatch.dispatched_tool_calls[0]["tool"] == "edit_file"

    # 3. ReAct State Adapter
    react = ReActStateAdapter()
    resp_react = react.invoke(node, ctx)
    assert resp_react.status == "COMPLETED"
    assert len(react.state_trace) > 0
    assert react.total_tokens_consumed > cli.total_tokens_consumed
