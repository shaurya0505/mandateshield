import pytest
from datetime import datetime, timezone
from domain.models.customer import Customer, CustomerRiskTier
from domain.models.mandate import Mandate, MandateStatus, PaymentMethod, IssuerBank
from domain.models.subscription import Subscription, SubscriptionStatus, BillingCycle
from domain.models.payment_attempt import PaymentAttempt, PaymentAttemptStatus, FailureCategory
from domain.models.recovery_case import RecoveryCase
from domain.models.recovery_context import RecoveryContext
from domain.interfaces.payment_provider import RailHealthMetrics
from services.ingestion.failure_normalizer import FailureNormalizer
from services.risk.revenue_risk_engine import RevenueRiskEngine
from services.signals.recovery_context_builder import RecoveryContextBuilder


def test_recovery_context_immutability_and_action_absence():
    """Invariant: RecoveryContext is strictly immutable and contains zero preselected recovery actions."""
    customer = Customer(
        id="cust_c1029",
        name="Rahul Mehta",
        email="rahul.mehta@example.com",
    )
    mandate_hdfc = Mandate(
        id="mnd_hdfc_01",
        customer_id=customer.id,
        provider_mandate_token="rzp_tok_hdfc",
        payment_method=PaymentMethod.CARD_MANDATE,
        issuer_bank=IssuerBank.HDFC,
        status=MandateStatus.ACTIVE,
        max_amount_in_paisa=1500000,
    )
    mandate_upi = Mandate(
        id="mnd_upi_02",
        customer_id=customer.id,
        provider_mandate_token="rzp_tok_upi",
        payment_method=PaymentMethod.UPI_AUTOPAY,
        issuer_bank=IssuerBank.ICICI,
        status=MandateStatus.ACTIVE,
        max_amount_in_paisa=1000000,
    )
    sub = Subscription(
        id="sub_1029",
        customer_id=customer.id,
        current_mandate_id=mandate_hdfc.id,
        amount_in_paisa=499900,
        billing_cycle=BillingCycle.MONTHLY,
        next_billing_at=datetime.now(timezone.utc),
    )
    case = RecoveryCase(
        id="case_1029",
        subscription_id=sub.id,
        customer_id=customer.id,
        initial_attempt_id="att_01",
        revenue_at_risk_in_paisa=499900,
    )
    normalized = FailureNormalizer.normalize("insufficient_funds", "Balance low")
    risk_assessment = RevenueRiskEngine.evaluate(
        subscription=sub,
        customer=customer,
        mandate=mandate_hdfc,
        failure_category=normalized.category,
    )
    rail_health = RailHealthMetrics(
        issuer_bank=IssuerBank.HDFC,
        payment_method=PaymentMethod.CARD_MANDATE,
        sample_window_minutes=60,
        total_attempts=10,
        successful_attempts=9,
        success_rate=0.90,
        is_degraded=False,
    )

    success_dates = [
        datetime(2026, 6, 2, 10, 0, 0, tzinfo=timezone.utc),
        datetime(2026, 7, 1, 10, 0, 0, tzinfo=timezone.utc),
        datetime(2026, 8, 1, 10, 0, 0, tzinfo=timezone.utc),
    ]

    context = RecoveryContextBuilder.build(
        recovery_case=case,
        customer=customer,
        subscription=sub,
        mandate=mandate_hdfc,
        normalized_failure=normalized,
        risk_assessment=risk_assessment,
        rail_health=rail_health,
        customer_mandates=[mandate_hdfc, mandate_upi],
        historical_successful_dates=success_dates,
        current_time=datetime(2026, 8, 28, 10, 0, 0, tzinfo=timezone.utc),
    )

    # Verify attributes
    assert context.recovery_case_id == "case_1029"
    assert context.amount_in_paisa == 499900
    assert context.has_alternative_active_mandate is True
    assert context.alternative_mandate_count == 1
    assert context.historical_timing_signal.has_timing_signal is True
    assert context.historical_timing_signal.in_current_window is False

    # Invariant: Verify context does not have a recovery action field
    assert not hasattr(context, "recovery_action")
    assert not hasattr(context, "proposed_action")
    assert not hasattr(context, "action")

    # Invariant: Verify immutability (frozen model)
    with pytest.raises(Exception):
        context.amount_in_paisa = 1000
