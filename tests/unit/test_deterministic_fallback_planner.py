from datetime import datetime, timezone
from domain.models.customer import Customer
from domain.models.mandate import Mandate, MandateStatus, PaymentMethod, IssuerBank
from domain.models.subscription import Subscription, BillingCycle
from domain.models.payment_attempt import FailureCategory
from domain.models.recovery_case import RecoveryCase
from domain.models.strategy_proposal import StrategyReasonCode, PlannerSource, StrategyProposal
from domain.states.recovery_state import RecoveryAction, RecoveryState
from domain.interfaces.payment_provider import RailHealthMetrics
from services.ingestion.failure_normalizer import FailureNormalizer
from services.risk.revenue_risk_engine import RevenueRiskEngine
from services.signals.recovery_context_builder import RecoveryContextBuilder
from services.ai.deterministic_fallback_planner import DeterministicFallbackPlanner


def _build_test_context(
    amount_in_paisa: int = 499900,
    raw_error: str = "insufficient_funds",
    mandate_status: MandateStatus = MandateStatus.ACTIVE,
    is_rail_degraded: bool = False,
    has_alt_mandate: bool = False,
    previous_attempt_count: int = 0,
    historical_dates: list = None,
    current_time: datetime = None,
):
    now = current_time or datetime(2026, 8, 28, 10, 0, 0, tzinfo=timezone.utc)
    customer = Customer(id="cust_fb_01", name="Test Customer", email="test@example.com")
    mandate = Mandate(
        id="mnd_fb_01",
        customer_id=customer.id,
        provider_mandate_token="rzp_tok_fb_01",
        payment_method=PaymentMethod.CARD_MANDATE,
        issuer_bank=IssuerBank.HDFC,
        status=mandate_status,
        max_amount_in_paisa=10000000,
    )
    mandates = [mandate]
    if has_alt_mandate:
        alt_mandate = Mandate(
            id="mnd_fb_02",
            customer_id=customer.id,
            provider_mandate_token="rzp_tok_fb_02",
            payment_method=PaymentMethod.UPI_AUTOPAY,
            issuer_bank=IssuerBank.ICICI,
            status=MandateStatus.ACTIVE,
            max_amount_in_paisa=10000000,
        )
        mandates.append(alt_mandate)

    sub = Subscription(
        id="sub_fb_01",
        customer_id=customer.id,
        current_mandate_id=mandate.id,
        amount_in_paisa=amount_in_paisa,
        billing_cycle=BillingCycle.MONTHLY,
        next_billing_at=now,
    )
    case = RecoveryCase(
        id="case_fb_01",
        subscription_id=sub.id,
        customer_id=customer.id,
        initial_attempt_id="att_fb_01",
        revenue_at_risk_in_paisa=amount_in_paisa,
        total_attempts=previous_attempt_count,
    )
    normalized = FailureNormalizer.normalize(raw_error)
    risk_assessment = RevenueRiskEngine.evaluate(
        subscription=sub,
        customer=customer,
        mandate=mandate,
        failure_category=normalized.category,
        prior_attempt_count=max(1, previous_attempt_count),
        is_rail_degraded=is_rail_degraded,
    )
    rail_health = RailHealthMetrics(
        issuer_bank=IssuerBank.HDFC,
        payment_method=PaymentMethod.CARD_MANDATE,
        sample_window_minutes=60,
        total_attempts=10,
        successful_attempts=2 if is_rail_degraded else 9,
        success_rate=0.20 if is_rail_degraded else 0.90,
        is_degraded=is_rail_degraded,
    )

    return RecoveryContextBuilder.build(
        recovery_case=case,
        customer=customer,
        subscription=sub,
        mandate=mandate,
        normalized_failure=normalized,
        risk_assessment=risk_assessment,
        rail_health=rail_health,
        customer_mandates=mandates,
        historical_successful_dates=historical_dates or [],
        current_time=now,
    )


def test_fallback_liquidity_timing_wait_and_retry():
    """Verify fallback proposes WAIT_AND_RETRY with strategy_confidence=None."""
    dates = [
        datetime(2026, 6, 2, 10, 0, 0, tzinfo=timezone.utc),
        datetime(2026, 7, 1, 10, 0, 0, tzinfo=timezone.utc),
        datetime(2026, 8, 1, 10, 0, 0, tzinfo=timezone.utc),
    ]
    context = _build_test_context(
        raw_error="insufficient_funds",
        historical_dates=dates,
        current_time=datetime(2026, 8, 28, 10, 0, 0, tzinfo=timezone.utc),
    )

    planner = DeterministicFallbackPlanner()
    proposal = planner.propose_strategy(context)

    assert proposal.action == RecoveryAction.WAIT_AND_RETRY
    assert StrategyReasonCode.INSUFFICIENT_FUNDS in proposal.reason_codes
    assert StrategyReasonCode.HISTORICAL_PAYMENT_WINDOW in proposal.reason_codes
    assert proposal.recommended_delay_seconds == 4 * 86400
    assert proposal.planner_source == PlannerSource.DETERMINISTIC_FALLBACK
    # Non-fabricated confidence for fallback
    assert proposal.strategy_confidence is None


def test_fallback_transient_error_retry_now():
    """Verify fallback proposes immediate RETRY_NOW with strategy_confidence=None."""
    context = _build_test_context(raw_error="bank_technical_error", previous_attempt_count=0)
    planner = DeterministicFallbackPlanner()
    proposal = planner.propose_strategy(context)

    assert proposal.action == RecoveryAction.RETRY_NOW
    assert StrategyReasonCode.TRANSIENT_PROVIDER_FAILURE in proposal.reason_codes
    assert proposal.recommended_delay_seconds == 0
    assert proposal.strategy_confidence is None


def test_fallback_rail_degradation_with_alternative_mandate():
    """Verify fallback proposes SWITCH_PAYMENT_PATH with strategy_confidence=None."""
    context = _build_test_context(
        raw_error="issuer_down",
        is_rail_degraded=True,
        has_alt_mandate=True,
    )
    planner = DeterministicFallbackPlanner()
    proposal = planner.propose_strategy(context)

    assert proposal.action == RecoveryAction.SWITCH_PAYMENT_PATH
    assert StrategyReasonCode.RAIL_DEGRADATION in proposal.reason_codes
    assert StrategyReasonCode.ACTIVE_ALTERNATIVE_MANDATE in proposal.reason_codes
    assert proposal.strategy_confidence is None


def test_fallback_rail_degradation_without_alternative_mandate():
    """Verify fallback proposes WAIT_AND_RETRY (4h cooldown) when rail is degraded and NO alternative exists."""
    context = _build_test_context(
        raw_error="issuer_down",
        is_rail_degraded=True,
        has_alt_mandate=False,
    )
    planner = DeterministicFallbackPlanner()
    proposal = planner.propose_strategy(context)

    assert proposal.action == RecoveryAction.WAIT_AND_RETRY
    assert StrategyReasonCode.RAIL_DEGRADATION in proposal.reason_codes
    assert proposal.recommended_delay_seconds == 14400
    assert proposal.strategy_confidence is None


def test_fallback_revoked_mandate_stops_recovery():
    """Verify fallback halts recovery on inactive/revoked mandate."""
    context = _build_test_context(
        raw_error="mandate_inactive",
        mandate_status=MandateStatus.REVOKED,
    )
    planner = DeterministicFallbackPlanner()
    proposal = planner.propose_strategy(context)

    assert proposal.action == RecoveryAction.STOP_RECOVERY
    assert StrategyReasonCode.MANDATE_INACTIVE in proposal.reason_codes
    assert proposal.strategy_confidence is None


def test_fallback_high_value_repeated_failure_escalation():
    """Verify high-value (₹30,000) repeated failure escalates to human ops."""
    context = _build_test_context(
        amount_in_paisa=3000000,
        raw_error="insufficient_funds",
        previous_attempt_count=2,
    )
    planner = DeterministicFallbackPlanner()
    proposal = planner.propose_strategy(context)

    assert proposal.action == RecoveryAction.ESCALATE_TO_HUMAN
    assert StrategyReasonCode.HIGH_VALUE_CASE in proposal.reason_codes
    assert StrategyReasonCode.HUMAN_REVIEW_REQUIRED in proposal.reason_codes
    assert proposal.strategy_confidence is None


def test_fallback_only_produces_advisory_proposal():
    """
    Security Invariant: DeterministicFallbackPlanner ONLY produces an advisory StrategyProposal.
    It does NOT authorize payments, execute charges, or mutate state.
    """
    context = _build_test_context(raw_error="insufficient_funds")
    planner = DeterministicFallbackPlanner()
    proposal = planner.propose_strategy(context)

    assert isinstance(proposal, StrategyProposal)
    assert not hasattr(proposal, "authorized_action")
    assert not hasattr(proposal, "policy_verdict")
    assert not hasattr(proposal, "is_authorized")
