from datetime import datetime, timezone
from domain.models.customer import Customer, CustomerRiskTier
from domain.models.mandate import Mandate, MandateStatus, PaymentMethod, IssuerBank
from domain.models.subscription import Subscription, SubscriptionStatus, BillingCycle
from domain.models.payment_attempt import FailureCategory
from services.risk.revenue_risk_engine import (
    RevenueRiskEngine,
    RevenueRiskAssessment,
    RecoveryPriorityLevel,
)


def _make_sample_entities(
    amount_in_paisa: int = 499900,
    cycle: BillingCycle = BillingCycle.MONTHLY,
    mandate_status: MandateStatus = MandateStatus.ACTIVE,
    risk_tier: CustomerRiskTier = CustomerRiskTier.STANDARD,
):
    customer = Customer(
        id="cust_test_101",
        name="Test User",
        email="test@example.com",
        risk_tier=risk_tier,
    )
    mandate = Mandate(
        id="mnd_test_101",
        customer_id=customer.id,
        provider_mandate_token="rzp_tok_test_101",
        payment_method=PaymentMethod.CARD_MANDATE,
        issuer_bank=IssuerBank.HDFC,
        status=mandate_status,
        max_amount_in_paisa=5000000,
    )
    subscription = Subscription(
        id="sub_test_101",
        customer_id=customer.id,
        current_mandate_id=mandate.id,
        amount_in_paisa=amount_in_paisa,
        billing_cycle=cycle,
        status=SubscriptionStatus.ACTIVE,
        next_billing_at=datetime.now(timezone.utc),
    )
    return customer, mandate, subscription


def test_annualized_revenue_calculation():
    """Verify integer paisa arithmetic for annualizing recurring subscription value."""
    # Monthly: ₹4,999 * 12 = ₹59,988 (5998800 paisa)
    assert RevenueRiskEngine.calculate_annualized_revenue(499900, BillingCycle.MONTHLY) == 5998800
    # Quarterly: ₹10,000 * 4 = ₹40,000 (4000000 paisa)
    assert RevenueRiskEngine.calculate_annualized_revenue(1000000, BillingCycle.QUARTERLY) == 4000000
    # Annual: ₹50,000 * 1 = ₹50,000 (5000000 paisa)
    assert RevenueRiskEngine.calculate_annualized_revenue(5000000, BillingCycle.ANNUAL) == 5000000


def test_standard_transient_failure_evaluation():
    """Verify high priority score for transient bank glitches on active mandates."""
    customer, mandate, sub = _make_sample_entities(amount_in_paisa=499900)
    
    assessment = RevenueRiskEngine.evaluate(
        subscription=sub,
        customer=customer,
        mandate=mandate,
        failure_category=FailureCategory.TRANSIENT_ISSUER_FAILURE,
        prior_attempt_count=1,
    )

    assert assessment.revenue_at_risk_in_paisa == 499900
    assert assessment.annualized_revenue_at_risk_in_paisa == 5998800
    assert assessment.priority_level in (RecoveryPriorityLevel.CRITICAL, RecoveryPriorityLevel.HIGH)
    assert assessment.recovery_potential_score >= 70.0
    assert assessment.is_high_value is False
    assert assessment.requires_human_escalation is False


def test_high_value_enterprise_escalation():
    """Verify high-value (> ₹25,000) subscriptions trigger CRITICAL priority and human escalation flag on repeated fail."""
    # ₹30,000 monthly subscription (3000000 paisa)
    customer, mandate, sub = _make_sample_entities(amount_in_paisa=3000000)
    
    # 2nd attempt failed
    assessment = RevenueRiskEngine.evaluate(
        subscription=sub,
        customer=customer,
        mandate=mandate,
        failure_category=FailureCategory.LIQUIDITY_FAILURE,
        prior_attempt_count=2,
    )

    assert assessment.is_high_value is True
    assert assessment.priority_level == RecoveryPriorityLevel.CRITICAL
    assert assessment.requires_human_escalation is True


def test_inactive_or_revoked_mandate_evaluation():
    """Verify revoked or inactive mandates yield NEGLIGIBLE priority and 0 score."""
    customer, mandate, sub = _make_sample_entities(
        amount_in_paisa=499900,
        mandate_status=MandateStatus.REVOKED,
    )

    assessment = RevenueRiskEngine.evaluate(
        subscription=sub,
        customer=customer,
        mandate=mandate,
        failure_category=FailureCategory.MANDATE_REVOKED,
        prior_attempt_count=1,
    )

    assert assessment.priority_level == RecoveryPriorityLevel.NEGLIGIBLE
    assert assessment.recovery_potential_score == 0.0


def test_attempt_decay_reduces_score():
    """Verify repeated failed recovery attempts decay recovery potential score."""
    customer, mandate, sub = _make_sample_entities(amount_in_paisa=199900)

    score_1 = RevenueRiskEngine.evaluate(
        subscription=sub, customer=customer, mandate=mandate,
        failure_category=FailureCategory.LIQUIDITY_FAILURE, prior_attempt_count=1
    ).recovery_potential_score

    score_2 = RevenueRiskEngine.evaluate(
        subscription=sub, customer=customer, mandate=mandate,
        failure_category=FailureCategory.LIQUIDITY_FAILURE, prior_attempt_count=2
    ).recovery_potential_score

    score_3 = RevenueRiskEngine.evaluate(
        subscription=sub, customer=customer, mandate=mandate,
        failure_category=FailureCategory.LIQUIDITY_FAILURE, prior_attempt_count=3
    ).recovery_potential_score

    assert score_1 > score_2 > score_3
