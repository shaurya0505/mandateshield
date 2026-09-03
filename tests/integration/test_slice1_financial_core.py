from domain.models.customer import CustomerRiskTier
from domain.models.mandate import IssuerBank, PaymentMethod
from domain.models.payment_attempt import FailureCategory
from domain.models.recovery_case import RecoveryCase
from domain.states.recovery_state import RecoveryState
from infrastructure.simulation.synthetic_scenario_generator import SyntheticScenarioGenerator
from services.ingestion.failure_normalizer import FailureNormalizer
from services.risk.revenue_risk_engine import RevenueRiskEngine, RecoveryPriorityLevel


def test_slice1_pipeline_insufficient_funds_to_risk_evaluation():
    """
    End-to-End Slice 1 Integration Test:
    1. Scenario: Insufficient funds on August 28th.
    2. Provider generates failure.
    3. FailureNormalizer standardizes the code.
    4. RevenueRiskEngine assesses financial exposure and recovery priority.
    5. RecoveryCase lifecycle initial state is created and validated.
    """
    setup = SyntheticScenarioGenerator.create_insufficient_funds_scenario(seed=42)

    # 1. Attempt charge on Simulated Payment Provider
    attempt_res = setup.provider.charge_mandate(
        mandate_token=setup.primary_mandate.provider_mandate_token,
        amount_in_paisa=setup.subscription.amount_in_paisa,
        idempotency_key="idemp_int_01",
    )
    assert attempt_res.success is False
    assert attempt_res.raw_error_code == "insufficient_funds"

    # 2. Ingest and Normalize failure
    normalized = FailureNormalizer.normalize(
        raw_error_code=attempt_res.raw_error_code,
        raw_error_message=attempt_res.raw_error_message,
        provenance="SIMULATED_PROVIDER",
    )
    assert normalized.category == FailureCategory.LIQUIDITY_FAILURE
    assert normalized.is_retryable_by_nature is True

    # 3. Assess Revenue Risk and Recovery Priority
    risk_assessment = RevenueRiskEngine.evaluate(
        subscription=setup.subscription,
        customer=setup.customer,
        mandate=setup.primary_mandate,
        failure_category=normalized.category,
        prior_attempt_count=1,
        in_historical_timing_window=False,  # Aug 28 is outside Day 1-4
    )
    assert risk_assessment.revenue_at_risk_in_paisa == 499900
    assert risk_assessment.annualized_revenue_at_risk_in_paisa == 5998800
    assert risk_assessment.priority_level in (RecoveryPriorityLevel.HIGH, RecoveryPriorityLevel.MEDIUM)
    assert risk_assessment.requires_human_escalation is False

    # 4. Open RecoveryCase and verify state transition invariants
    case = RecoveryCase(
        id="case_int_01",
        subscription_id=setup.subscription.id,
        customer_id=setup.customer.id,
        initial_attempt_id="att_int_01",
        revenue_at_risk_in_paisa=risk_assessment.revenue_at_risk_in_paisa,
        status=RecoveryState.PAYMENT_FAILED,
    )
    assert case.status == RecoveryState.PAYMENT_FAILED

    # Transition to RECOVERY_ELIGIBLE
    case.transition_to(RecoveryState.RECOVERY_ELIGIBLE)
    assert case.status == RecoveryState.RECOVERY_ELIGIBLE


def test_slice1_pipeline_rail_degradation_handling():
    """
    End-to-End Slice 1 Integration Test for Rail Degradation:
    Provider rail health detected -> Outage failure normalized -> Risk evaluated with penalty.
    """
    setup = SyntheticScenarioGenerator.create_rail_degradation_scenario(seed=42)

    # Rail health check
    health = setup.provider.get_rail_health(IssuerBank.SBI, PaymentMethod.UPI_AUTOPAY)
    assert health.is_degraded is True

    # Failed charge on degraded rail
    attempt_res = setup.provider.charge_mandate(
        mandate_token=setup.mandates[0].provider_mandate_token,
        amount_in_paisa=setup.subscription.amount_in_paisa,
        idempotency_key="idemp_int_02",
    )
    assert attempt_res.success is False

    # Normalization
    normalized = FailureNormalizer.normalize(
        raw_error_code=attempt_res.raw_error_code,
        raw_error_message=attempt_res.raw_error_message,
    )
    assert normalized.category == FailureCategory.TRANSIENT_ISSUER_FAILURE

    # Risk Engine evaluation reflects degraded rail
    risk_assessment = RevenueRiskEngine.evaluate(
        subscription=setup.subscription,
        customer=setup.customer,
        mandate=setup.mandates[0],
        failure_category=normalized.category,
        is_rail_degraded=True,
    )
    assert risk_assessment.explainable_factors["is_rail_degraded"] is True


def test_slice1_pipeline_revoked_mandate_terminal_protection():
    """
    End-to-End Slice 1 Integration Test for Revoked Mandate:
    Failure normalized to MANDATE_REVOKED -> Priority NEGLIGIBLE -> State transitions safely to STOPPED.
    """
    setup = SyntheticScenarioGenerator.create_revoked_mandate_scenario(seed=42)

    attempt_res = setup.provider.charge_mandate(
        mandate_token=setup.primary_mandate.provider_mandate_token,
        amount_in_paisa=setup.subscription.amount_in_paisa,
        idempotency_key="idemp_int_03",
    )
    assert attempt_res.success is False

    normalized = FailureNormalizer.normalize(attempt_res.raw_error_code, attempt_res.raw_error_message)
    assert normalized.category == FailureCategory.MANDATE_REVOKED
    assert normalized.is_retryable_by_nature is False

    risk_assessment = RevenueRiskEngine.evaluate(
        subscription=setup.subscription,
        customer=setup.customer,
        mandate=setup.primary_mandate,
        failure_category=normalized.category,
    )
    assert risk_assessment.priority_level == RecoveryPriorityLevel.NEGLIGIBLE
    assert risk_assessment.recovery_potential_score == 0.0

    # Invariant: Revoked cases transition directly to STOPPED
    case = RecoveryCase(
        id="case_int_03",
        subscription_id=setup.subscription.id,
        customer_id=setup.customer.id,
        initial_attempt_id="att_int_03",
        revenue_at_risk_in_paisa=risk_assessment.revenue_at_risk_in_paisa,
        status=RecoveryState.PAYMENT_FAILED,
    )
    case.transition_to(RecoveryState.STOPPED)
    assert case.status == RecoveryState.STOPPED
    assert case.closed_at is not None
