"""Focused unit tests for calibrated fault matrix runner and defect-sensitivity evaluation.

Asserts exact row counts, operator round-robin scheduling, actual mutated failure
semantics, deterministic ordering, immutability, and timeout handling.
"""

from __future__ import annotations

import json
import pytest

from dafg.eval import BenchmarkTask, StandardOutcome
from dafg.fault_matrix import (
    FaultMatrixResult,
    FaultMatrixRow,
    ROUND_ROBIN_OPERATORS,
    run_calibrated_fault_matrix,
)
from dafg.faults import (
    CLASS_1_SYNTAX_PACKAGING,
    CLASS_2_SUBTLE_LOGIC,
    logic_flip,
    syntax_break,
)


@pytest.fixture
def pilot_tasks():
    """Pair of feasible and impossible tasks for matrix verification."""
    feasible = BenchmarkTask(
        task_id="pilot_feas_1",
        title="Feasible State Task",
        is_feasible=True,
        test_fixture="def test_add():\n    assert 1 + 1 == 2\ntest_add()\n",
        cohort="protocol",
    )
    impossible = BenchmarkTask(
        task_id="pilot_imp_1",
        title="Impossible Constraint Task",
        is_feasible=False,
        test_fixture="# impossible\nassert budget > 100 and budget < 10\n",
        cohort="impossible",
    )
    return [feasible, impossible]


def test_exact_row_counts_and_operator_round_robin():
    """Assert exact row counts (2 per feasible, 1 per impossible) and round-robin operators."""
    feasible_tasks = [
        BenchmarkTask(
            task_id=f"feas_{i}",
            title=f"Feasible Task {i}",
            is_feasible=True,
            test_fixture="def test_ok():\n    assert 1 == 1\ntest_ok()\n",
            cohort="protocol",
        )
        for i in range(7)
    ]
    impossible_tasks = [
        BenchmarkTask(
            task_id=f"imp_{i}",
            title=f"Impossible Task {i}",
            is_feasible=False,
            test_fixture="print('impossible')\n",
            cohort="impossible",
        )
        for i in range(2)
    ]

    # Interleave impossible tasks between feasible tasks
    tasks = [
        feasible_tasks[0],
        impossible_tasks[0],
        feasible_tasks[1],
        feasible_tasks[2],
        feasible_tasks[3],
        feasible_tasks[4],
        feasible_tasks[5],
        impossible_tasks[1],
        feasible_tasks[6],
    ]

    res = run_calibrated_fault_matrix(tasks)

    # 7 feasible * 2 rows + 2 impossible * 1 row = 16 rows
    assert len(res) == 16
    assert res.total_trials == 16
    assert res.summary["total_rows"] == 16
    assert res.summary["total_tasks"] == 9
    assert res.summary["original_count"] == 7
    assert res.summary["mutated_count"] == 7
    assert res.summary["impossible_count"] == 2

    # Verify per-task row variants and round-robin operator distribution
    mutated_operators = [r.operator for r in res if r.variant == "mutated"]
    expected_round_robin = [
        ROUND_ROBIN_OPERATORS[i % len(ROUND_ROBIN_OPERATORS)][0] for i in range(7)
    ]
    assert mutated_operators == expected_round_robin

    # Impossible tasks must not consume operator slots or mutate
    impossible_rows = [r for r in res if r.variant == "impossible"]
    assert len(impossible_rows) == 2
    for imp_row in impossible_rows:
        assert imp_row.operator is None
        assert imp_row.fault is None
        assert imp_row.correct_block is True
        assert imp_row.is_feasible is False


def test_actual_mutated_failure_semantics():
    """Verify actual subprocess execution, exit codes, and failure semantics for mutations."""
    # 1. Syntax break mutation causes compile/parse failure in subprocess (exit code != 0)
    task_syntax = BenchmarkTask(
        task_id="t_syntax",
        title="Syntax Mutation Task",
        is_feasible=True,
        test_fixture="def test_add():\n    assert 1 + 1 == 2\ntest_add()\n",
        cohort="protocol",
    )
    res_syntax = run_calibrated_fault_matrix(
        [task_syntax], operators={"syntax_break": syntax_break}
    )
    assert len(res_syntax) == 2
    orig_row, mut_row = res_syntax[0], res_syntax[1]

    # Original passes cleanly
    assert orig_row.variant == "original"
    assert orig_row.exit_code == 0
    assert orig_row.passed is True
    assert orig_row.verified is True
    assert orig_row.verified_outcome == "VERIFIED_SUCCESS"
    assert orig_row.standard_outcome == StandardOutcome.VERIFIED_SUCCESS.value
    assert orig_row.false_completion is False
    assert orig_row.detectable_by_gate is False

    # Mutated fails in subprocess with non-zero exit and gate detection
    assert mut_row.variant == "mutated"
    assert mut_row.exit_code != 0
    assert mut_row.passed is False
    assert mut_row.verified is False
    assert mut_row.verified_outcome == "VERIFIED_FAILURE"
    assert mut_row.standard_outcome == StandardOutcome.VERIFIED_FAILURE.value
    assert mut_row.false_completion is True
    assert mut_row.detectable_by_gate is True
    assert mut_row.operator == "syntax_break"
    assert mut_row.fault_class == str(CLASS_1_SYNTAX_PACKAGING)
    assert "SyntaxError" in mut_row.expected_failure

    # 2. Logic flip mutation inverts assertions and causes assertion failure in subprocess
    task_logic = BenchmarkTask(
        task_id="t_logic",
        title="Logic Mutation Task",
        is_feasible=True,
        test_fixture="assert 1 + 1 == 2\n",
        cohort="protocol",
    )
    res_logic = run_calibrated_fault_matrix(
        [task_logic], operators={"logic_flip": logic_flip}
    )
    orig_l, mut_l = res_logic[0], res_logic[1]

    assert orig_l.exit_code == 0
    assert orig_l.passed is True

    assert mut_l.exit_code != 0
    assert mut_l.passed is False
    assert mut_l.verified is False
    assert mut_l.verified_outcome == "VERIFIED_FAILURE"
    assert mut_l.standard_outcome == StandardOutcome.VERIFIED_FAILURE.value
    assert mut_l.false_completion is True
    assert mut_l.detectable_by_gate is True
    assert mut_l.operator == "logic_flip"
    assert mut_l.fault_class == str(CLASS_2_SUBTLE_LOGIC)
    assert "AssertionError" in mut_l.expected_failure

    # 3. Impossible task produces exactly one correct-block row
    task_imp = BenchmarkTask(
        task_id="t_imp",
        title="Impossible Task",
        is_feasible=False,
        test_fixture="# impossible\nassert 1 == 2\n",
        cohort="impossible",
    )
    res_imp = run_calibrated_fault_matrix([task_imp])
    assert len(res_imp) == 1
    imp_row = res_imp[0]
    assert imp_row.variant == "impossible"
    assert imp_row.is_feasible is False
    assert imp_row.correct_block is True
    assert imp_row.verified is True
    assert imp_row.verified_outcome == "CORRECT_BLOCK"
    assert imp_row.standard_outcome == StandardOutcome.CORRECT_BLOCK.value
    assert imp_row.completion_claim == "BLOCKED"
    assert imp_row.false_completion is False
    assert imp_row.detectable_by_gate is True
    assert imp_row.operator is None


def test_deterministic_ordering(pilot_tasks):
    """Verify sequential matrix executions produce identical task and operator order."""
    res1 = run_calibrated_fault_matrix(pilot_tasks, seed=42)
    res2 = run_calibrated_fault_matrix(pilot_tasks, seed=42)

    rows1 = [
        (
            r.task_id,
            r.variant,
            r.operator,
            r.exit_code,
            r.passed,
            r.standard_outcome,
            r.detectable_by_gate,
            r.false_completion,
            r.correct_block,
        )
        for r in res1
    ]
    rows2 = [
        (
            r.task_id,
            r.variant,
            r.operator,
            r.exit_code,
            r.passed,
            r.standard_outcome,
            r.detectable_by_gate,
            r.false_completion,
            r.correct_block,
        )
        for r in res2
    ]
    assert rows1 == rows2
    assert res1.summary == res2.summary
    assert res1.by_fault_class == res2.by_fault_class
    assert res1.by_cohort == res2.by_cohort


def test_input_immutability(pilot_tasks):
    """Verify running the matrix preserves input task properties and operators mapping."""
    orig_fixtures = [t.test_fixture for t in pilot_tasks]
    orig_feasibility = [t.is_feasible for t in pilot_tasks]
    orig_cohorts = [t.cohort for t in pilot_tasks]
    orig_ids = [t.task_id for t in pilot_tasks]
    orig_titles = [t.title for t in pilot_tasks]

    custom_ops = {"syntax_break": syntax_break, "logic_flip": logic_flip}
    custom_ops_copy = dict(custom_ops)

    res = run_calibrated_fault_matrix(pilot_tasks, operators=custom_ops)

    # Assert results recorded properly
    assert len(res) == 3  # 1 feasible * 2 + 1 impossible * 1 = 3

    # Assert original tasks were never mutated
    assert [t.test_fixture for t in pilot_tasks] == orig_fixtures
    assert [t.is_feasible for t in pilot_tasks] == orig_feasibility
    assert [t.cohort for t in pilot_tasks] == orig_cohorts
    assert [t.task_id for t in pilot_tasks] == orig_ids
    assert [t.title for t in pilot_tasks] == orig_titles
    assert custom_ops == custom_ops_copy


def test_timeout_handling():
    """Verify subprocess execution timeout is intercepted and recorded as exit code 124."""
    task_timeout = BenchmarkTask(
        task_id="t_timeout",
        title="Timeout Task",
        is_feasible=True,
        test_fixture="import time\ntime.sleep(2)\n",
        cohort="edge_cases",
    )

    # Execute with an aggressive 0.1s timeout
    res = run_calibrated_fault_matrix([task_timeout], timeout=0.1)

    assert len(res) == 2
    row_orig = res[0]
    assert row_orig.variant == "original"
    assert row_orig.exit_code == 124
    assert row_orig.passed is False
    assert "TimeoutExpired" in row_orig.stderr
    assert row_orig.verified is False
    assert row_orig.verified_outcome == "VERIFIED_FAILURE"
    assert row_orig.false_completion is True


def test_fault_matrix_result_container():
    """Verify FaultMatrixResult and FaultMatrixRow container access semantics and JSON serialization."""
    task = BenchmarkTask(
        task_id="t_container",
        title="Container Test Task",
        is_feasible=True,
        test_fixture="assert 1 == 1\n",
        cohort="test",
    )
    res = run_calibrated_fault_matrix([task])

    assert isinstance(res, FaultMatrixResult)
    assert len(res) == 2
    assert isinstance(res[0], FaultMatrixRow)

    # Check attribute and dict-style key access
    assert res.total_trials == 2
    assert res["total_trials"] == 2
    assert res.summary == res["summary"]
    assert res.by_fault_class == res["by_fault_class"]

    row = res[0]
    assert row.variant == "original"
    assert row["variant"] == "original"

    # Verify JSON serialization
    serialized = res.to_dict()
    assert isinstance(serialized, dict)
    assert "rows" in serialized
    assert "summary" in serialized
    assert "by_fault_class" in serialized
    json_str = json.dumps(serialized, indent=2)
    assert len(json_str) > 0
