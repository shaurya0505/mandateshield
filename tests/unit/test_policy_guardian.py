from datetime import datetime, timedelta, timezone
from unittest.mock import patch
import pytest

from domain.models.customer import Customer, CustomerRiskTier
from domain.models.mandate import Mandate, MandateStatus, PaymentMethod, IssuerBank
from domain.models.subscription import Subscription, BillingCycle
from domain.models.payment_attempt import FailureCategory
from domain.models.recovery_case import RecoveryCase
from domain.models.strategy_proposal import StrategyProposal, StrategyReasonCode, PlannerSource
from domain.models.policy_authorization import PolicyVerdict, PolicyAuthorization
from domain.policies.policy_config import PolicyConfig
from domain.policies.policy_evaluation import PolicyEvaluation
from domain.policies.rule_types import RuleCategory
from domain.states.recovery_state import RecoveryAction, RecoveryState, RecoveryStateMachine
from domain.interfaces.payment_provider import RailHealthMetrics
from services.ingestion.failure_normalizer import FailureNormalizer
from services.risk.revenue_risk_engine import RevenueRiskEngine
from services.signals.recovery_context_builder import RecoveryContextBuilder
from services.policy.policy_guardian import PolicyGuardian


def _create_context_and_proposal(
    action: RecoveryAction = RecoveryAction.RETRY_NOW,
    amount_in_paisa: int = 499900,
    max_amount_in_paisa: int = 10000000,
    mandate_status: MandateStatus = MandateStatus.ACTIVE,
    case_attempts: int = 0,
    nudges_sent: int = 0,
    has_alt_mandate: bool = False,
    last_attempt_time: datetime = None,
    current_time: datetime = None,
    strategy_confidence: float = 0.90,
):
    now = current_time or datetime(2026, 9, 2, 10, 0, 0, tzinfo=timezone.utc)
    customer = Customer(id="cust_pol_01", name="Test Customer", email="test@example.com")
    mandate = Mandate(
        id="mnd_pol_01",
        customer_id=customer.id,
        provider_mandate_token="rzp_tok_pol_01",
        payment_method=PaymentMethod.CARD_MANDATE,
        issuer_bank=IssuerBank.HDFC,
        status=mandate_status,
        max_amount_in_paisa=max_amount_in_paisa,
    )
    mandates = [mandate]
    if has_alt_mandate:
        alt_mandate = Mandate(
            id="mnd_pol_02",
            customer_id=customer.id,
            provider_mandate_token="rzp_tok_pol_02",
            payment_method=PaymentMethod.UPI_AUTOPAY,
            issuer_bank=IssuerBank.ICICI,
            status=MandateStatus.ACTIVE,
            max_amount_in_paisa=max_amount_in_paisa,
        )
        mandates.append(alt_mandate)

    sub = Subscription(
        id="sub_pol_01",
        customer_id=customer.id,
        current_mandate_id=mandate.id,
        amount_in_paisa=amount_in_paisa,
        billing_cycle=BillingCycle.MONTHLY,
        next_billing_at=now,
    )
    case = RecoveryCase(
        id="case_pol_01",
        subscription_id=sub.id,
        customer_id=customer.id,
        initial_attempt_id="att_pol_01",
        revenue_at_risk_in_paisa=amount_in_paisa,
        total_attempts=case_attempts,
        total_nudges_sent=nudges_sent,
        last_attempt_at=last_attempt_time,
    )
    normalized = FailureNormalizer.normalize("insufficient_funds")
    risk_assessment = RevenueRiskEngine.evaluate(
        subscription=sub,
        customer=customer,
        mandate=mandate,
        failure_category=normalized.category,
        prior_attempt_count=max(1, case_attempts),
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

    context = RecoveryContextBuilder.build(
        recovery_case=case,
        customer=customer,
        subscription=sub,
        mandate=mandate,
        normalized_failure=normalized,
        risk_assessment=risk_assessment,
        rail_health=rail_health,
        customer_mandates=mandates,
        current_time=now,
    )

    proposal = StrategyProposal(
        proposal_id="prop_test_01",
        recovery_case_id=case.id,
        subscription_id=sub.id,
        action=action,
        reason_codes=[StrategyReasonCode.TRANSIENT_PROVIDER_FAILURE],
        rationale="AI recommended action based on context.",
        strategy_confidence=strategy_confidence,
        planner_source=PlannerSource.GEMINI_LLM,
        generated_at=now,
    )

    return context, proposal, case


def test_valid_retry_now_approved():
    """Verify valid RETRY_NOW on active mandate within limits is APPROVED with PolicyAuthorization."""
    context, proposal, _ = _create_context_and_proposal(action=RecoveryAction.RETRY_NOW)
    guardian = PolicyGuardian()
    evaluation = guardian.evaluate(context, proposal)

    assert evaluation.is_approved is True
    assert evaluation.verdict == PolicyVerdict.APPROVED
    assert evaluation.authorization is not None
    assert evaluation.authorization.authorized_action == RecoveryAction.RETRY_NOW
    assert evaluation.authorization.decision_id == proposal.proposal_id
    assert evaluation.authorization.case_id == context.recovery_case_id
    assert evaluation.authorization.execution_parameters["amount_in_paisa"] == 499900


def test_terminal_case_state_rejected():
    """Invariant: Cases in terminal states (RECOVERED or STOPPED) cannot receive authorization."""
    context, proposal, _ = _create_context_and_proposal(action=RecoveryAction.RETRY_NOW)
    guardian = PolicyGuardian()

    # Terminal RECOVERED
    eval_recovered = guardian.evaluate(context, proposal, case_status=RecoveryState.RECOVERED)
    assert eval_recovered.is_approved is False
    assert eval_recovered.verdict == PolicyVerdict.REJECTED
    assert eval_recovered.authorization is None
    assert any("terminal state 'RECOVERED'" in r for r in eval_recovered.rejection_reasons)

    # Terminal STOPPED
    eval_stopped = guardian.evaluate(context, proposal, case_status=RecoveryState.STOPPED)
    assert eval_stopped.is_approved is False
    assert eval_stopped.verdict == PolicyVerdict.REJECTED
    assert eval_stopped.authorization is None


def test_inactive_and_revoked_mandate_debit_rejected():
    """Invariant: Direct debit attempts on inactive or revoked mandates are blocked (PROVIDER_RULE)."""
    context, proposal, _ = _create_context_and_proposal(
        action=RecoveryAction.RETRY_NOW,
        mandate_status=MandateStatus.REVOKED,
    )
    guardian = PolicyGuardian()
    evaluation = guardian.evaluate(context, proposal)

    assert evaluation.is_approved is False
    assert evaluation.verdict == PolicyVerdict.REJECTED
    assert evaluation.authorization is None
    assert any("Mandate status is 'REVOKED'" in r for r in evaluation.rejection_reasons)


def test_retry_limit_exceeded_rejected():
    """Invariant: Attempting debit after reaching max retries (3) is blocked (MERCHANT_POLICY)."""
    context, proposal, _ = _create_context_and_proposal(
        action=RecoveryAction.RETRY_NOW,
        case_attempts=3,  # Max allowed is 3
    )
    guardian = PolicyGuardian()
    evaluation = guardian.evaluate(context, proposal)

    assert evaluation.is_approved is False
    assert evaluation.verdict == PolicyVerdict.REJECTED
    assert any("Maximum retry threshold" in r for r in evaluation.rejection_reasons)


def test_retry_cooldown_violation_rejected():
    """Invariant: Attempting RETRY_NOW before 24h cooldown has elapsed is blocked (MERCHANT_POLICY)."""
    now = datetime(2026, 9, 2, 12, 0, 0, tzinfo=timezone.utc)
    last_attempt = now - timedelta(hours=4)  # Only 4 hours elapsed (24h required)

    context, proposal, _ = _create_context_and_proposal(
        action=RecoveryAction.RETRY_NOW,
        case_attempts=1,
        last_attempt_time=last_attempt,
        current_time=now,
    )
    guardian = PolicyGuardian()
    evaluation = guardian.evaluate(context, proposal)

    assert evaluation.is_approved is False
    assert evaluation.verdict == PolicyVerdict.REJECTED
    assert any("Retry cooldown period has not elapsed" in r for r in evaluation.rejection_reasons)


def test_amount_exceeds_mandate_max_rejected():
    """Invariant: Charge amount exceeding mandate max limit is blocked (PROVIDER_RULE)."""
    context, proposal, _ = _create_context_and_proposal(
        action=RecoveryAction.RETRY_NOW,
        amount_in_paisa=5000000,      # ₹50,000
        max_amount_in_paisa=2000000,  # ₹20,000 max
    )
    guardian = PolicyGuardian()
    evaluation = guardian.evaluate(context, proposal)

    assert evaluation.is_approved is False
    assert any("exceeds mandate max limit" in r for r in evaluation.rejection_reasons)


def test_high_value_transaction_repeated_failure_escalated():
    """Invariant: Repeated failure on high-value subscription (> ₹25,000) requires ESCALATION."""
    context, proposal, _ = _create_context_and_proposal(
        action=RecoveryAction.RETRY_NOW,
        amount_in_paisa=3000000,  # ₹30,000
        case_attempts=1,          # Repeat failure
    )
    guardian = PolicyGuardian()
    evaluation = guardian.evaluate(context, proposal)

    assert evaluation.is_approved is False
    assert evaluation.verdict == PolicyVerdict.ESCALATED
    assert evaluation.authorization is None
    assert any("High-value transaction repeat failure requires human concierge escalation" in r for r in evaluation.rejection_reasons)


def test_customer_contact_nudge_limit_enforced():
    """Invariant: SEND_RECOVERY_NUDGE is blocked when notification limit (2) is reached."""
    # Under limit (1 nudge sent) -> Approved
    context_ok, proposal_ok, _ = _create_context_and_proposal(
        action=RecoveryAction.SEND_RECOVERY_NUDGE,
        nudges_sent=1,
    )
    guardian = PolicyGuardian()
    eval_ok = guardian.evaluate(context_ok, proposal_ok)
    assert eval_ok.is_approved is True
    assert eval_ok.authorization.authorized_action == RecoveryAction.SEND_RECOVERY_NUDGE

    # Over limit (2 nudges sent) -> Rejected
    context_limit, proposal_limit, _ = _create_context_and_proposal(
        action=RecoveryAction.SEND_RECOVERY_NUDGE,
        nudges_sent=2,
    )
    eval_limit = guardian.evaluate(context_limit, proposal_limit)
    assert eval_limit.is_approved is False
    assert any("Customer notification limit" in r for r in eval_limit.rejection_reasons)


def test_switch_payment_path_mandate_verification():
    """Verify SWITCH_PAYMENT_PATH requires verified active alternative mandate."""
    # Without alternate mandate -> Rejected
    context_no_alt, proposal_no_alt, _ = _create_context_and_proposal(
        action=RecoveryAction.SWITCH_PAYMENT_PATH,
        has_alt_mandate=False,
    )
    guardian = PolicyGuardian()
    eval_no_alt = guardian.evaluate(context_no_alt, proposal_no_alt)
    assert eval_no_alt.is_approved is False
    assert any("no verified active alternative payment method" in r for r in eval_no_alt.rejection_reasons)

    # With alternate mandate -> Approved
    context_alt, proposal_alt, _ = _create_context_and_proposal(
        action=RecoveryAction.SWITCH_PAYMENT_PATH,
        has_alt_mandate=True,
    )
    eval_alt = guardian.evaluate(context_alt, proposal_alt)
    assert eval_alt.is_approved is True
    assert eval_alt.authorization.authorized_action == RecoveryAction.SWITCH_PAYMENT_PATH


def test_safe_non_debit_actions_approved():
    """Verify safe non-debit actions (WAIT_AND_RETRY, ESCALATE_TO_HUMAN, STOP_RECOVERY) are approved."""
    guardian = PolicyGuardian()

    for action in (RecoveryAction.WAIT_AND_RETRY, RecoveryAction.ESCALATE_TO_HUMAN, RecoveryAction.STOP_RECOVERY):
        context, proposal, _ = _create_context_and_proposal(action=action)
        evaluation = guardian.evaluate(context, proposal)
        assert evaluation.is_approved is True
        assert evaluation.authorization.authorized_action == action


def test_ai_confidence_and_rationale_cannot_bypass_policy():
    """
    Security Invariant: High LLM confidence (0.99) and persuasive rationale CANNOT bypass failed policies.
    """
    context, proposal, _ = _create_context_and_proposal(
        action=RecoveryAction.RETRY_NOW,
        mandate_status=MandateStatus.REVOKED,
        strategy_confidence=0.99,
    )
    guardian = PolicyGuardian()
    evaluation = guardian.evaluate(context, proposal)

    # Despite 99% confidence, policy guardian strictly rejects
    assert evaluation.is_approved is False
    assert evaluation.authorization is None


def test_rule_provenance_preservation():
    """Verify all evaluated rules carry explicit provenance categories."""
    context, proposal, _ = _create_context_and_proposal(action=RecoveryAction.RETRY_NOW)
    guardian = PolicyGuardian()
    evaluation = guardian.evaluate(context, proposal)

    categories = {rule.category for rule in evaluation.evaluated_rules}
    assert RuleCategory.PROVIDER_RULE in categories
    assert RuleCategory.MERCHANT_POLICY in categories
    assert RuleCategory.SIMULATION_POLICY in categories


def test_amount_integrity_cannot_be_tampered_by_ai():
    """
    Security Invariant: Authorization parameters strictly pull amount from trusted RecoveryContext.
    AI proposal does not possess an amount field and cannot modify the financial debit value.
    """
    context, proposal, _ = _create_context_and_proposal(
        action=RecoveryAction.RETRY_NOW,
        amount_in_paisa=499900,  # ₹4,999.00
    )
    guardian = PolicyGuardian()
    evaluation = guardian.evaluate(context, proposal)

    assert evaluation.is_approved is True
    assert evaluation.authorization.execution_parameters["amount_in_paisa"] == 499900
    assert not hasattr(proposal, "amount_in_paisa")
    assert not hasattr(proposal, "amount")


def test_unexpected_evaluation_error_fails_closed():
    """
    Security Invariant: Any unexpected internal exception fails closed immediately.
    No authorization is generated, verdict is REJECTED, and error is recorded.
    """
    context, proposal, _ = _create_context_and_proposal(action=RecoveryAction.RETRY_NOW)
    guardian = PolicyGuardian()

    # Simulate an unexpected runtime error inside the evaluation loop
    with patch.object(RecoveryStateMachine, "is_terminal", side_effect=RuntimeError("Database connection lost")):
        evaluation = guardian.evaluate(context, proposal)

    assert evaluation.is_approved is False
    assert evaluation.verdict == PolicyVerdict.REJECTED
    assert evaluation.authorization is None
    assert any("Unexpected policy evaluation error" in r for r in evaluation.rejection_reasons)


def test_authorization_identity_and_validity_binding():
    """Verify PolicyAuthorization binds exact case, proposal ID, action, and TTL."""
    now = datetime(2026, 9, 2, 10, 0, 0, tzinfo=timezone.utc)
    context, proposal, _ = _create_context_and_proposal(
        action=RecoveryAction.RETRY_NOW,
        current_time=now,
    )
    config = PolicyConfig(authorization_validity_seconds=1800)  # 30 min TTL
    guardian = PolicyGuardian(config=config)
    evaluation = guardian.evaluate(context, proposal)

    auth = evaluation.authorization
    assert auth is not None
    assert auth.case_id == context.recovery_case_id
    assert auth.decision_id == proposal.proposal_id
    assert auth.authorized_action == RecoveryAction.RETRY_NOW
    assert auth.valid_until == now + timedelta(seconds=1800)
    assert auth.is_valid_for_execution(now) is True
    # Expired after 31 minutes
    assert auth.is_valid_for_execution(now + timedelta(minutes=31)) is False
