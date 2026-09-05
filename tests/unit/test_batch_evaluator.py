import pytest
from domain.models.evaluation import EvaluationPolicy
from domain.states.recovery_state import RecoveryAction
from services.evaluation.batch_evaluator import BatchEvaluator


def test_batch_evaluator_execution_and_metrics():
    """Verify batch evaluation computes summaries and comparative lift across all three policies."""
    evaluator = BatchEvaluator()
    result = evaluator.evaluate(seed=42, scenario_count=18)

    assert result.scenario_count == 18
    assert len(result.paired_results) == 18

    # Summaries for all three policies
    summary_no = result.policy_summaries[EvaluationPolicy.NO_RECOVERY]
    summary_fixed = result.policy_summaries[EvaluationPolicy.FIXED_RETRY]
    summary_ms = result.policy_summaries[EvaluationPolicy.MANDATESHIELD]

    assert summary_no.eligible_cases == 18
    assert summary_no.recovered_cases == 0
    assert summary_no.gross_recovered_amount_in_paisa == 0

    assert summary_fixed.eligible_cases == 18
    assert summary_fixed.total_retries > 0

    assert summary_ms.eligible_cases == 18
    assert summary_ms.gross_recovered_amount_in_paisa > 0
    assert summary_ms.unnecessary_retries_count < summary_fixed.unnecessary_retries_count
    assert summary_ms.customer_contact_index < summary_fixed.customer_contact_index

    # Action distribution proves MandateShield is NOT blindly retrying everything
    assert RecoveryAction.WAIT_AND_RETRY in summary_ms.action_distribution
    assert RecoveryAction.STOP_RECOVERY in summary_ms.action_distribution
    assert RecoveryAction.ESCALATE_TO_HUMAN in summary_ms.action_distribution

    # Comparative Lift Metrics
    lift = result.lift_metrics
    assert lift.gross_recovery_lift_vs_no_recovery_in_paisa == summary_ms.gross_recovered_amount_in_paisa
    assert lift.retries_avoided_vs_fixed_retry >= 0


def test_batch_evaluator_deterministic_reproducibility():
    """Invariant: Running BatchEvaluator twice with the exact same seed produces 100% identical results."""
    evaluator = BatchEvaluator()

    run1 = evaluator.evaluate(seed=1337, scenario_count=12)
    run2 = evaluator.evaluate(seed=1337, scenario_count=12)

    # Validate exact monetary equality
    assert run1.policy_summaries[EvaluationPolicy.MANDATESHIELD].gross_recovered_amount_in_paisa == (
        run2.policy_summaries[EvaluationPolicy.MANDATESHIELD].gross_recovered_amount_in_paisa
    )
    assert run1.policy_summaries[EvaluationPolicy.MANDATESHIELD].net_recovered_amount_in_paisa == (
        run2.policy_summaries[EvaluationPolicy.MANDATESHIELD].net_recovered_amount_in_paisa
    )
    assert run1.policy_summaries[EvaluationPolicy.FIXED_RETRY].gross_recovered_amount_in_paisa == (
        run2.policy_summaries[EvaluationPolicy.FIXED_RETRY].gross_recovered_amount_in_paisa
    )
    assert run1.lift_metrics.gross_recovery_lift_vs_fixed_retry_in_paisa == (
        run2.lift_metrics.gross_recovery_lift_vs_fixed_retry_in_paisa
    )
