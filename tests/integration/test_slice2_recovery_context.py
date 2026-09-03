from datetime import datetime, timezone
from domain.models.mandate import IssuerBank, PaymentMethod, MandateStatus
from domain.models.payment_attempt import FailureCategory
from domain.models.recovery_case import RecoveryCase
from domain.states.recovery_state import RecoveryState
from infrastructure.simulation.synthetic_scenario_generator import SyntheticScenarioGenerator
from services.ingestion.failure_normalizer import FailureNormalizer
from services.risk.revenue_risk_engine import RevenueRiskEngine
from services.signals.recovery_context_builder import RecoveryContextBuilder


def test_slice2_pipeline_liquidity_failure_to_recovery_context():
    """
    End-to-End Slice 2 Context Integration Test:
    Simulated Failure -> Normalizer -> Risk Engine -> Historical Timing Extractor -> RecoveryContext.
    """
    setup = SyntheticScenarioGenerator.create_insufficient_funds_scenario(seed=42)

    # 1. Trigger simulated charge on Aug 28
    attempt_res = setup.provider.charge_mandate(
        mandate_token=setup.primary_mandate.provider_mandate_token,
        amount_in_paisa=setup.subscription.amount_in_paisa,
        idempotency_key="idemp_ctx_01",
    )
    assert attempt_res.success is False

    # 2. Normalize Failure
    normalized = FailureNormalizer.normalize(
        raw_error_code=attempt_res.raw_error_code,
        raw_error_message=attempt_res.raw_error_message,
    )
    assert normalized.category == FailureCategory.LIQUIDITY_FAILURE

    # 3. Assess Risk & Priority
    risk_assessment = RevenueRiskEngine.evaluate(
        subscription=setup.subscription,
        customer=setup.customer,
        mandate=setup.primary_mandate,
        failure_category=normalized.category,
    )

    # 4. Fetch Rail Health
    rail_health = setup.provider.get_rail_health(
        issuer_bank=setup.primary_mandate.issuer_bank,
        payment_method=setup.primary_mandate.payment_method,
    )

    # 5. Open Recovery Case
    case = RecoveryCase(
        id="case_ctx_01",
        subscription_id=setup.subscription.id,
        customer_id=setup.customer.id,
        initial_attempt_id="att_ctx_01",
        revenue_at_risk_in_paisa=risk_assessment.revenue_at_risk_in_paisa,
        status=RecoveryState.PAYMENT_FAILED,
    )
    case.transition_to(RecoveryState.RECOVERY_ELIGIBLE)

    # 6. Build Historical Successful Dates (Simulated Past Cycles on June 2, July 1, Aug 1)
    past_success_dates = [
        datetime(2026, 6, 2, 10, 0, 0, tzinfo=timezone.utc),
        datetime(2026, 7, 1, 10, 0, 0, tzinfo=timezone.utc),
        datetime(2026, 8, 1, 10, 0, 0, tzinfo=timezone.utc),
    ]

    # 7. Construct Immutable RecoveryContext
    context = RecoveryContextBuilder.build(
        recovery_case=case,
        customer=setup.customer,
        subscription=setup.subscription,
        mandate=setup.primary_mandate,
        normalized_failure=normalized,
        risk_assessment=risk_assessment,
        rail_health=rail_health,
        customer_mandates=setup.mandates,
        historical_successful_dates=past_success_dates,
        current_time=setup.clock.now(),
    )

    # Assertions on RecoveryContext facts
    assert context.recovery_case_id == "case_ctx_01"
    assert context.amount_in_paisa == 499900
    assert context.normalized_failure_category == FailureCategory.LIQUIDITY_FAILURE
    assert context.is_mandate_chargeable is True
    assert context.historical_timing_signal.has_timing_signal is True
    assert context.historical_timing_signal.window_start_day == 1
    assert context.historical_timing_signal.window_end_day == 2
    assert context.historical_timing_signal.in_current_window is False
    assert context.historical_timing_signal.days_until_next_window == 4
    assert context.is_rail_degraded is False


def test_slice2_pipeline_rail_degradation_to_recovery_context():
    """
    End-to-End Slice 2 Context Integration Test with Active Rail Degradation & Alternate Mandate.
    """
    setup = SyntheticScenarioGenerator.create_rail_degradation_scenario(seed=42)

    # Primary SBI mandate fails
    attempt_res = setup.provider.charge_mandate(
        mandate_token=setup.mandates[0].provider_mandate_token,
        amount_in_paisa=setup.subscription.amount_in_paisa,
        idempotency_key="idemp_ctx_sbi",
    )
    normalized = FailureNormalizer.normalize(attempt_res.raw_error_code, attempt_res.raw_error_message)

    rail_health = setup.provider.get_rail_health(
        issuer_bank=setup.mandates[0].issuer_bank,
        payment_method=setup.mandates[0].payment_method,
    )
    assert rail_health.is_degraded is True

    risk_assessment = RevenueRiskEngine.evaluate(
        subscription=setup.subscription,
        customer=setup.customer,
        mandate=setup.mandates[0],
        failure_category=normalized.category,
        is_rail_degraded=True,
    )

    case = RecoveryCase(
        id="case_ctx_02",
        subscription_id=setup.subscription.id,
        customer_id=setup.customer.id,
        initial_attempt_id="att_ctx_02",
        revenue_at_risk_in_paisa=risk_assessment.revenue_at_risk_in_paisa,
    )

    context = RecoveryContextBuilder.build(
        recovery_case=case,
        customer=setup.customer,
        subscription=setup.subscription,
        mandate=setup.mandates[0],
        normalized_failure=normalized,
        risk_assessment=risk_assessment,
        rail_health=rail_health,
        customer_mandates=setup.mandates,  # Contains alternate ICICI mandate
        current_time=setup.clock.now(),
    )

    assert context.is_rail_degraded is True
    assert context.has_alternative_active_mandate is True
    assert context.alternative_mandate_count == 1
    assert context.mandate_status == MandateStatus.ACTIVE
