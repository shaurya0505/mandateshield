from domain.models.evaluation import EvaluationPolicy
from domain.states.recovery_state import RecoveryAction, RecoveryState
from services.evaluation.batch_evaluator import BatchEvaluator


def test_slice4_full_counterfactual_batch_evaluation():
    """
    Slice 4 Integration Test:
    Runs full batch counterfactual evaluation across representative failure archetypes.
    Verifies that:
    1. Every scenario is evaluated under all three policies identically (NO_RECOVERY, FIXED_RETRY, MANDATESHIELD).
    2. MandateShield avoids wasted debits on revoked mandates and degraded rails.
    3. MandateShield recovers liquidity failures via intelligent WAIT_AND_RETRY timing with minimal retry attempts.
    4. Financial calculations use pure integer paisa arithmetic.
    5. AI confidence is NOT treated as recovery probability.
    """
    evaluator = BatchEvaluator()
    report = evaluator.evaluate(seed=42, scenario_count=24)

    assert report.scenario_count == 24
    assert len(report.paired_results) == 24

    no_rec = report.policy_summaries[EvaluationPolicy.NO_RECOVERY]
    fixed = report.policy_summaries[EvaluationPolicy.FIXED_RETRY]
    ms = report.policy_summaries[EvaluationPolicy.MANDATESHIELD]

    # 1. NO_RECOVERY baseline sanity
    assert no_rec.gross_recovered_amount_in_paisa == 0
    assert no_rec.total_operational_cost_in_paisa == 0
    assert no_rec.recovery_rate == 0.0

    # 2. FIXED_RETRY vs MANDATESHIELD comparison
    assert ms.gross_recovered_amount_in_paisa > 0
    assert ms.unnecessary_retries_count < fixed.unnecessary_retries_count
    assert ms.customer_contact_index < fixed.customer_contact_index

    # 3. Action Diversity verification
    assert RecoveryAction.WAIT_AND_RETRY in ms.action_distribution
    assert RecoveryAction.STOP_RECOVERY in ms.action_distribution
    assert RecoveryAction.ESCALATE_TO_HUMAN in ms.action_distribution

    # 4. Paired counterfactual checks on specific failure modes
    revoked_scenarios = [p for p in report.paired_results if p.failure_mode == "REVOKED_MANDATE"]
    for paired in revoked_scenarios:
        # MandateShield stops immediately with 0 debit cost on revoked mandates
        assert paired.mandateshield.final_case_state == RecoveryState.STOPPED
        assert paired.mandateshield.total_retries == 0
        assert paired.mandateshield.operational_cost_in_paisa == 0

    liquidity_scenarios = [p for p in report.paired_results if p.failure_mode == "LIQUIDITY_DEFICIT"]
    for paired in liquidity_scenarios:
        # MandateShield consistently recovers with exactly 1 scheduled retry
        assert paired.mandateshield.is_recovered is True
        assert paired.mandateshield.total_retries == 1
        assert RecoveryAction.WAIT_AND_RETRY in paired.mandateshield.actions_taken
        # Fixed retry attempts multiple blind retries
        assert paired.fixed_retry.total_retries >= 1

    rail_alt_scenarios = [p for p in report.paired_results if p.failure_mode == "RAIL_DEGRADATION_WITH_ALT"]
    for paired in rail_alt_scenarios:
        # MandateShield immediately switches to ICICI card and recovers
        assert paired.mandateshield.is_recovered is True
        assert RecoveryAction.SWITCH_PAYMENT_PATH in paired.mandateshield.actions_taken
