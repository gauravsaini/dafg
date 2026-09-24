"""Unit tests for Phase 1 verification-first comparison module.

Tests use three EvaluationTrial objects to verify calculation of baseline success,
verified outcomes, false completion rate, correct block rate, and delivery rate.
Stdlib-only using unittest.
"""

import unittest

from dafg.eval import CompletionClaim, EvaluationTrial, StandardOutcome
from dafg.phase1_compare import run_comparison, summarize_comparison


class TestPhase1Comparison(unittest.TestCase):
    def setUp(self) -> None:
        # Exactly three EvaluationTrial objects as specified in requirements:
        # Trial 1: Feasible task, agent claims SUCCESS, judge verifies SUCCESS.
        self.trial_verified_success = EvaluationTrial(
            trial_id="trial_1",
            task_id="task_feasible_1",
            condition="control_plane_v1",
            is_feasible=True,
            completion_claim=CompletionClaim.SUCCESS,
            standard_outcome=StandardOutcome.VERIFIED_SUCCESS,
        )

        # Trial 2: Feasible task, agent claims SUCCESS, judge detects failure (false completion).
        self.trial_false_completion = EvaluationTrial(
            trial_id="trial_2",
            task_id="task_feasible_2",
            condition="control_plane_v1",
            is_feasible=True,
            completion_claim=CompletionClaim.SUCCESS,
            standard_outcome=StandardOutcome.VERIFIED_FAILURE,
        )

        # Trial 3: Impossible task, agent blocks/refutes, judge confirms correct block.
        self.trial_correct_block = EvaluationTrial(
            trial_id="trial_3",
            task_id="task_impossible_1",
            condition="control_plane_v1",
            is_feasible=False,
            completion_claim=CompletionClaim.BLOCKED,
            standard_outcome=StandardOutcome.CORRECT_BLOCK,
        )

        self.three_trials = [
            self.trial_verified_success,
            self.trial_false_completion,
            self.trial_correct_block,
        ]

    def test_summarize_comparison_three_trials(self) -> None:
        """Verify metric calculations with three EvaluationTrial objects."""
        summary = summarize_comparison(self.three_trials, threshold=10.0)

        # Denominators
        self.assertEqual(summary["total_trials"], 3)
        self.assertEqual(summary["feasible_trials"], 2)
        self.assertEqual(summary["impossible_trials"], 1)

        # Baseline success (counts self-reported CompletionClaim.SUCCESS)
        # Trial 1 (SUCCESS) + Trial 2 (SUCCESS) = 2
        self.assertEqual(summary["baseline_success_count"], 2)
        self.assertAlmostEqual(summary["baseline_success_rate"], 2 / 3)

        # Verified outcomes (VERIFIED_SUCCESS and CORRECT_BLOCK)
        # Trial 1 (VERIFIED_SUCCESS) + Trial 3 (CORRECT_BLOCK) = 2
        self.assertEqual(summary["verified_success_count"], 1)
        self.assertEqual(summary["correct_block_count"], 1)
        self.assertEqual(summary["verified_outcomes_count"], 2)
        self.assertAlmostEqual(summary["verified_outcome_rate"], 2 / 3)

        # Delivery rate (VERIFIED_SUCCESS / feasible_trials = 1 / 2 = 0.5)
        self.assertAlmostEqual(summary["delivery_rate"], 0.5)
        self.assertAlmostEqual(summary["delivery_success_rate"], 0.5)

        # Correct block rate (CORRECT_BLOCK / impossible_trials = 1 / 1 = 1.0)
        self.assertAlmostEqual(summary["correct_block_rate"], 1.0)

        # False completion (claimed SUCCESS but not VERIFIED_SUCCESS: Trial 2)
        self.assertEqual(summary["false_completion_count"], 1)
        self.assertAlmostEqual(summary["false_completion_rate"], 1 / 3)
        self.assertAlmostEqual(summary["false_claim_rate"], 0.5)

    def test_run_comparison_delegates_to_summarize_comparison(self) -> None:
        """Verify run_comparison delegates to summarize_comparison."""
        summary_direct = summarize_comparison(self.three_trials, threshold=10.0)
        summary_delegated = run_comparison(self.three_trials, threshold=10.0)
        self.assertEqual(summary_direct, summary_delegated)

    def test_oracle_pass_rates_within_threshold(self) -> None:
        """Verify oracle pass rate comparison when within threshold."""
        # Expected delivery rate matches actual 0.5 (50%), diff = 0% <= threshold (10.0%)
        summary = summarize_comparison(self.three_trials, oracle_pass_rates=0.5, threshold=10.0)
        self.assertTrue(summary["within_threshold"])
        self.assertAlmostEqual(summary["oracle_diff"], 0.0)

    def test_oracle_pass_rates_exceeds_threshold(self) -> None:
        """Verify oracle pass rate comparison when exceeding threshold."""
        # Expected delivery rate 0.9 (90%), actual is 0.5 (50%), diff = 40% > threshold (10.0%)
        summary = summarize_comparison(self.three_trials, oracle_pass_rates=0.9, threshold=10.0)
        self.assertFalse(summary["within_threshold"])
        self.assertAlmostEqual(summary["oracle_diff"], 40.0)

    def test_matrix_input_format(self) -> None:
        """Verify matrix format (dict of condition -> list of trials)."""
        matrix = {"control_plane_v1": self.three_trials}
        summary = summarize_comparison(matrix)
        self.assertEqual(summary["total_trials"], 3)
        self.assertAlmostEqual(summary["delivery_rate"], 0.5)
        self.assertIn("control_plane_v1", summary["by_condition"])
        arm_summary = summary["by_condition"]["control_plane_v1"]
        self.assertEqual(arm_summary["verified_outcomes_count"], 2)

    def test_empty_trials_returns_zero_rates(self) -> None:
        """Verify zero-division safe behavior when trial list is empty."""
        summary = summarize_comparison([])
        self.assertEqual(summary["total_trials"], 0)
        self.assertEqual(summary["delivery_rate"], 0.0)
        self.assertEqual(summary["correct_block_rate"], 0.0)
        self.assertEqual(summary["false_completion_rate"], 0.0)
        self.assertEqual(summary["baseline_success_rate"], 0.0)


if __name__ == "__main__":
    unittest.main()
