import pytest
from domain.models.evaluation import (
    EvaluationPolicy,
    ScenarioOutcome,
    PolicyMetricSummary,
    LiftMetrics,
)
from domain.states.recovery_state import RecoveryAction, RecoveryState
from services.evaluation.metrics_calculator import MetricsCalculator


def test_metrics_calculator_single_policy_summary():
    """Verify gross recovery, net recovery, recovery rates, and contact index calculations."""
    outcomes = [
        ScenarioOutcome(
            scenario_id="s1",
            scenario_name="Scenario 1",
            policy=EvaluationPolicy.MANDATESHIELD,
            initial_amount_at_risk_in_paisa=500000,  # ₹5,000
            gross_recovered_amount_in_paisa=500000,
            operational_cost_in_paisa=500,          # ₹5
            net_recovered_amount_in_paisa=499500,
            is_recovered=True,
            final_case_state=RecoveryState.RECOVERED,
            total_retries=1,
            total_nudges=0,
            unnecessary_retries=0,
            actions_taken=[RecoveryAction.WAIT_AND_RETRY, RecoveryAction.RETRY_NOW],
        ),
        ScenarioOutcome(
            scenario_id="s2",
            scenario_name="Scenario 2",
            policy=EvaluationPolicy.MANDATESHIELD,
            initial_amount_at_risk_in_paisa=300000,  # ₹3,000
            gross_recovered_amount_in_paisa=0,
            operational_cost_in_paisa=0,
            net_recovered_amount_in_paisa=0,
            is_recovered=False,
            final_case_state=RecoveryState.STOPPED,
            total_retries=0,
            total_nudges=0,
            unnecessary_retries=0,
            actions_taken=[RecoveryAction.STOP_RECOVERY],
        ),
    ]

    summary = MetricsCalculator.compute_policy_summary(EvaluationPolicy.MANDATESHIELD, outcomes)

    assert summary.eligible_cases == 2
    assert summary.recovered_cases == 1
    assert summary.recovery_rate == 0.50  # 1/2
    assert summary.total_revenue_at_risk_in_paisa == 800000
    assert summary.gross_recovered_amount_in_paisa == 500000
    assert summary.total_operational_cost_in_paisa == 500
    assert summary.net_recovered_amount_in_paisa == 499500
    assert summary.value_weighted_recovery_rate == 0.625  # 500k / 800k
    assert summary.total_retries == 1
    assert summary.customer_contact_index == 1.0  # 1 retry * 1.0
    assert summary.action_distribution[RecoveryAction.WAIT_AND_RETRY] == 1
    assert summary.action_distribution[RecoveryAction.STOP_RECOVERY] == 1


def test_lift_metrics_calculation_and_zero_baseline():
    """Verify lift calculations handle zero baseline gracefully without division by zero."""
    no_rec = PolicyMetricSummary(
        policy=EvaluationPolicy.NO_RECOVERY,
        eligible_cases=10,
        recovered_cases=0,
        recovery_rate=0.0,
        total_revenue_at_risk_in_paisa=10000000,
        gross_recovered_amount_in_paisa=0,
        net_recovered_amount_in_paisa=0,
        value_weighted_recovery_rate=0.0,
        total_operational_cost_in_paisa=0,
        total_retries=0,
        total_nudges=0,
        unnecessary_retries_count=0,
        customer_contact_index=0.0,
        action_distribution={},
    )

    fixed = PolicyMetricSummary(
        policy=EvaluationPolicy.FIXED_RETRY,
        eligible_cases=10,
        recovered_cases=4,
        recovery_rate=0.40,
        total_revenue_at_risk_in_paisa=10000000,
        gross_recovered_amount_in_paisa=4000000,
        net_recovered_amount_in_paisa=3985000,
        value_weighted_recovery_rate=0.40,
        total_operational_cost_in_paisa=15000,
        total_retries=30,
        total_nudges=0,
        unnecessary_retries_count=18,
        customer_contact_index=30.0,
        action_distribution={RecoveryAction.RETRY_NOW: 30},
    )

    ms = PolicyMetricSummary(
        policy=EvaluationPolicy.MANDATESHIELD,
        eligible_cases=10,
        recovered_cases=8,
        recovery_rate=0.80,
        total_revenue_at_risk_in_paisa=10000000,
        gross_recovered_amount_in_paisa=8000000,
        net_recovered_amount_in_paisa=7996000,
        value_weighted_recovery_rate=0.80,
        total_operational_cost_in_paisa=4000,
        total_retries=8,
        total_nudges=0,
        unnecessary_retries_count=0,
        customer_contact_index=8.0,
        action_distribution={RecoveryAction.WAIT_AND_RETRY: 5, RecoveryAction.RETRY_NOW: 8},
    )

    lift = MetricsCalculator.compute_lift_metrics(ms, no_rec, fixed)

    # Absolute lift vs NO_RECOVERY
    assert lift.gross_recovery_lift_vs_no_recovery_in_paisa == 8000000
    assert lift.net_recovery_lift_vs_no_recovery_in_paisa == 7996000
    assert lift.percentage_lift_vs_no_recovery is None  # Baseline is 0 -> None (not infinity)

    # Comparative lift vs FIXED_RETRY
    assert lift.gross_recovery_lift_vs_fixed_retry_in_paisa == 4000000
    assert lift.net_recovery_lift_vs_fixed_retry_in_paisa == 4011000
    assert lift.percentage_lift_vs_fixed_retry == 100.0  # (8M - 4M)/4M * 100% = 100%
    assert lift.recovery_rate_lift_vs_fixed_retry == 40.0  # 80% - 40% = 40 percentage points
    assert lift.retries_avoided_vs_fixed_retry == 22      # 30 - 8 = 22
    assert lift.contact_reduction_vs_fixed_retry == 22.0
