import pytest
from datetime import datetime, timezone
from domain.models.customer import Customer, CustomerRiskTier
from domain.models.mandate import Mandate, MandateStatus, PaymentMethod, IssuerBank
from domain.models.subscription import Subscription, SubscriptionStatus, BillingCycle
from domain.models.payment_attempt import PaymentAttempt, PaymentAttemptStatus, FailureCategory
from domain.models.policy_authorization import PolicyAuthorization, PolicyVerdict
from domain.models.recovery_case import RecoveryCase
from domain.states.recovery_state import RecoveryAction, RecoveryState
from domain.policies.rule_types import RuleCategory, EvaluatedRuleResult
from domain.events.recovery_events import PaymentFailedEvent, PaymentRecoveredEvent


def test_customer_creation():
    customer = Customer(
        id="cust_101",
        name="Shaurya Sharma",
        email="shaurya@example.com",
        risk_tier=CustomerRiskTier.STANDARD,
    )
    assert customer.id == "cust_101"
    assert customer.email == "shaurya@example.com"
    assert customer.risk_tier == CustomerRiskTier.STANDARD


def test_mandate_chargeability_and_validation():
    mandate = Mandate(
        id="mnd_101",
        customer_id="cust_101",
        provider_mandate_token="rzp_tok_99182",
        payment_method=PaymentMethod.UPI_AUTOPAY,
        issuer_bank=IssuerBank.HDFC,
        status=MandateStatus.ACTIVE,
        max_amount_in_paisa=1000000,  # ₹10,000 max
    )
    # Chargeable for ₹4,999 (499900 paisa)
    assert mandate.is_chargeable(499900) is True
    # Not chargeable for ₹15,000 (1500000 paisa) exceeding max amount
    assert mandate.is_chargeable(1500000) is False

    # Negative or zero max amount must fail validation
    with pytest.raises(ValueError):
        Mandate(
            id="mnd_inv",
            customer_id="cust_101",
            provider_mandate_token="rzp_tok_invalid",
            payment_method=PaymentMethod.UPI_AUTOPAY,
            issuer_bank=IssuerBank.HDFC,
            max_amount_in_paisa=0,
        )


def test_subscription_amount_validation():
    sub = Subscription(
        id="sub_101",
        customer_id="cust_101",
        current_mandate_id="mnd_101",
        amount_in_paisa=499900,  # ₹4,999.00
        billing_cycle=BillingCycle.MONTHLY,
        next_billing_at=datetime.now(timezone.utc),
    )
    assert sub.amount_in_paisa == 499900

    # Negative amount validation
    with pytest.raises(ValueError):
        Subscription(
            id="sub_inv",
            customer_id="cust_101",
            current_mandate_id="mnd_101",
            amount_in_paisa=-500,
            next_billing_at=datetime.now(timezone.utc),
        )


def test_recovery_case_net_recovery_calculation():
    case = RecoveryCase(
        id="case_201",
        subscription_id="sub_101",
        customer_id="cust_101",
        initial_attempt_id="att_101",
        revenue_at_risk_in_paisa=499900,
        status=RecoveryState.PAYMENT_FAILED,
    )

    # Record 2 retries (₹5 each = 500 paisa each) and 1 nudge (₹2 = 200 paisa)
    case.record_cost(500)
    case.record_cost(500)
    case.record_cost(200)
    assert case.recovery_cost_in_paisa == 1200  # ₹12 total cost

    # Advance state to RECOVERY_ELIGIBLE -> RECOVERY_ATTEMPTED (with auth) -> RECOVERED
    case.transition_to(RecoveryState.RECOVERY_ELIGIBLE)
    case.transition_to(RecoveryState.RECOVERY_ATTEMPTED, has_authorization=True)
    case.mark_recovered(amount_in_paisa=499900)

    assert case.recovered_amount_in_paisa == 499900
    # Net Recovery = 499900 - 1200 = 498700 paisa (₹4,987.00)
    assert case.net_recovered_paisa == 498700


def test_policy_authorization_model():
    rule_res = EvaluatedRuleResult(
        rule_id="RULE-PROV-01",
        rule_name="Mandate Status Check",
        category=RuleCategory.PROVIDER_RULE,
        passed=True,
        description="Mandate is active.",
    )
    auth = PolicyAuthorization(
        auth_id="auth_101",
        case_id="case_201",
        decision_id="dec_101",
        authorized_action=RecoveryAction.WAIT_AND_RETRY,
        verdict=PolicyVerdict.APPROVED,
        evaluated_rules=[rule_res],
        valid_until=datetime(2099, 1, 1, tzinfo=timezone.utc),
    )
    assert auth.is_valid_for_execution() is True
    assert auth.evaluated_rules[0].category == RuleCategory.PROVIDER_RULE


def test_domain_events_immutability():
    evt = PaymentFailedEvent(
        attempt_id="att_101",
        subscription_id="sub_101",
        customer_id="cust_101",
        mandate_id="mnd_101",
        amount_in_paisa=499900,
        raw_error_code="insufficient_funds",
        raw_error_message="Account balance inadequate for debit.",
    )
    assert evt.event_name == "payment.failed"
    assert evt.amount_in_paisa == 499900

    # Event is frozen
    with pytest.raises(Exception):
        evt.amount_in_paisa = 1000
