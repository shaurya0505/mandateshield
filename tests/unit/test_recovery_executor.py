from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock
import pytest

from domain.models.customer import Customer
from domain.models.mandate import Mandate, MandateStatus, PaymentMethod, IssuerBank
from domain.models.subscription import Subscription, BillingCycle
from domain.models.payment_attempt import PaymentAttemptStatus, FailureCategory
from domain.models.policy_authorization import PolicyAuthorization, PolicyVerdict
from domain.models.recovery_case import RecoveryCase
from domain.models.execution_result import ExecutionStatus
from domain.states.recovery_state import RecoveryAction, RecoveryState
from domain.interfaces.payment_provider import ProviderPaymentResult, ProviderPaymentLinkResult
from infrastructure.simulation.simulated_payment_provider import SimulatedPaymentProvider
from infrastructure.simulation.simulation_clock import SimulationClock
from services.executor.recovery_executor import RecoveryExecutor


def _build_test_entities(
    action: RecoveryAction = RecoveryAction.RETRY_NOW,
    amount_in_paisa: int = 499900,
    case_status: RecoveryState = RecoveryState.RECOVERY_ELIGIBLE,
    mandate_status: MandateStatus = MandateStatus.ACTIVE,
    is_approved: bool = True,
    auth_valid_minutes: int = 60,
    current_time: datetime = None,
    alt_mandate_status: MandateStatus = MandateStatus.ACTIVE,
):
    now = current_time or datetime(2026, 9, 2, 10, 0, 0, tzinfo=timezone.utc)
    customer = Customer(id="cust_exec_01", name="Exec Customer", email="exec@example.com")
    mandate = Mandate(
        id="mnd_exec_01",
        customer_id=customer.id,
        provider_mandate_token="rzp_tok_exec_01",
        payment_method=PaymentMethod.CARD_MANDATE,
        issuer_bank=IssuerBank.HDFC,
        status=mandate_status,
        max_amount_in_paisa=10000000,
    )
    alt_mandate = Mandate(
        id="mnd_exec_02",
        customer_id=customer.id,
        provider_mandate_token="rzp_tok_exec_02",
        payment_method=PaymentMethod.UPI_AUTOPAY,
        issuer_bank=IssuerBank.ICICI,
        status=alt_mandate_status,
        max_amount_in_paisa=10000000,
    )
    sub = Subscription(
        id="sub_exec_01",
        customer_id=customer.id,
        current_mandate_id=mandate.id,
        amount_in_paisa=amount_in_paisa,
        billing_cycle=BillingCycle.MONTHLY,
        next_billing_at=now,
    )
    case = RecoveryCase(
        id="case_exec_01",
        subscription_id=sub.id,
        customer_id=customer.id,
        initial_attempt_id="att_exec_init",
        revenue_at_risk_in_paisa=amount_in_paisa,
        status=case_status,
        total_attempts=0,
    )
    authorization = PolicyAuthorization(
        auth_id="auth_test_01",
        case_id=case.id,
        decision_id="prop_test_01",
        authorized_action=action,
        verdict=PolicyVerdict.APPROVED if is_approved else PolicyVerdict.REJECTED,
        valid_until=now + timedelta(minutes=auth_valid_minutes),
        execution_parameters={"amount_in_paisa": amount_in_paisa},
        created_at=now,
    )

    clock = SimulationClock(initial_time=now)
    provider = SimulatedPaymentProvider(clock=clock, seed=42)
    provider.register_mandate(mandate)
    provider.register_mandate(alt_mandate)

    return customer, sub, mandate, alt_mandate, case, authorization, provider, now


def test_valid_retry_now_successful_recovery():
    """Verify valid RETRY_NOW executes payment against provider and marks case RECOVERED."""
    customer, sub, mandate, _, case, auth, provider, now = _build_test_entities()
    executor = RecoveryExecutor()

    # Seed 42 on HDFC card has > 90% success
    result = executor.execute(auth, case, customer, sub, mandate, provider, now)

    assert result.success is True
    assert result.status == ExecutionStatus.SUCCESS
    assert result.amount_in_paisa == 499900
    assert result.operational_cost_in_paisa == 500  # ₹5.00 debit fee
    assert result.payment_attempt is not None
    assert result.payment_attempt.status == PaymentAttemptStatus.SUCCESS
    assert case.status == RecoveryState.RECOVERED
    assert case.recovered_amount_in_paisa == 499900
    assert case.recovery_cost_in_paisa == 500
    assert case.total_attempts == 1


def test_missing_or_rejected_authorization_fails_closed():
    """Invariant: Unapproved authorization is blocked; ZERO provider calls occur."""
    customer, sub, mandate, _, case, auth, provider, now = _build_test_entities(is_approved=False)
    executor = RecoveryExecutor()

    result = executor.execute(auth, case, customer, sub, mandate, provider, now)

    assert result.success is False
    assert result.status == ExecutionStatus.REJECTED_PRECONDITION
    assert len(provider._attempt_ledger) == 0
    assert case.status == RecoveryState.RECOVERY_ELIGIBLE


def test_expired_authorization_fails_closed():
    """Invariant: Expired authorization is blocked; ZERO provider calls occur."""
    customer, sub, mandate, _, case, auth, provider, now = _build_test_entities(auth_valid_minutes=-5)
    executor = RecoveryExecutor()

    result = executor.execute(auth, case, customer, sub, mandate, provider, now)

    assert result.success is False
    assert result.status == ExecutionStatus.REJECTED_PRECONDITION
    assert "expired" in result.error_message.lower()
    assert len(provider._attempt_ledger) == 0


def test_case_mismatch_fails_closed():
    """Invariant: Authorization with mismatched case_id is blocked."""
    customer, sub, mandate, _, case, auth, provider, now = _build_test_entities()
    # Tamper with case id
    mismatched_auth = auth.model_copy(update={"case_id": "case_other_99"})
    executor = RecoveryExecutor()

    result = executor.execute(mismatched_auth, case, customer, sub, mandate, provider, now)

    assert result.success is False
    assert result.status == ExecutionStatus.REJECTED_PRECONDITION
    assert "does not match Case" in result.error_message
    assert len(provider._attempt_ledger) == 0


def test_amount_mismatch_fails_closed():
    """Invariant: Authorization amount differing from subscription amount is blocked."""
    customer, sub, mandate, _, case, auth, provider, now = _build_test_entities()
    # Authorized amount is ₹1,000 while subscription is ₹4,999
    tampered_auth = auth.model_copy(update={"execution_parameters": {"amount_in_paisa": 100000}})
    executor = RecoveryExecutor()

    result = executor.execute(tampered_auth, case, customer, sub, mandate, provider, now)

    assert result.success is False
    assert result.status == ExecutionStatus.REJECTED_PRECONDITION
    assert "does not match subscription amount" in result.error_message
    assert len(provider._attempt_ledger) == 0


def test_terminal_case_execution_blocked():
    """Invariant: Cannot execute actions on already RECOVERED or STOPPED cases."""
    customer, sub, mandate, _, case, auth, provider, now = _build_test_entities(case_status=RecoveryState.RECOVERED)
    executor = RecoveryExecutor()

    result = executor.execute(auth, case, customer, sub, mandate, provider, now)

    assert result.success is False
    assert result.status == ExecutionStatus.REJECTED_PRECONDITION
    assert "terminal state 'RECOVERED'" in result.error_message
    assert len(provider._attempt_ledger) == 0


def test_stale_mandate_revocation_at_execution_time():
    """Invariant: Mandate revoked between authorization and execution fails closed."""
    customer, sub, mandate, _, case, auth, provider, now = _build_test_entities(mandate_status=MandateStatus.REVOKED)
    executor = RecoveryExecutor()

    result = executor.execute(auth, case, customer, sub, mandate, provider, now)

    assert result.success is False
    assert result.status == ExecutionStatus.REJECTED_PRECONDITION
    assert "REVOKED" in result.error_message
    assert len(provider._attempt_ledger) == 0


def test_idempotency_duplicate_call_returns_cached_result():
    """Invariant: Executing the same authorization twice results in EXACTLY ONE provider debit."""
    customer, sub, mandate, _, case, auth, provider, now = _build_test_entities()
    executor = RecoveryExecutor()

    # Call 1: Successful debit
    res1 = executor.execute(auth, case, customer, sub, mandate, provider, now)
    assert res1.success is True
    assert res1.status == ExecutionStatus.SUCCESS
    assert len(provider._attempt_ledger) == 1

    # Call 2: Duplicate invocation with identical authorization
    res2 = executor.execute(auth, case, customer, sub, mandate, provider, now)
    assert res2.success is True
    assert res2.status == ExecutionStatus.ALREADY_CONSUMED
    assert res2.operational_cost_in_paisa == 0  # No double charging of operational fee
    # Invariant: No second provider debit
    assert len(provider._attempt_ledger) == 1


def test_switch_payment_path_execution():
    """Verify SWITCH_PAYMENT_PATH debits alternative mandate and updates subscription."""
    customer, sub, mandate, alt_mandate, case, auth, provider, now = _build_test_entities(
        action=RecoveryAction.SWITCH_PAYMENT_PATH
    )
    executor = RecoveryExecutor()

    result = executor.execute(auth, case, customer, sub, mandate, provider, now, alternative_mandate=alt_mandate)

    assert result.success is True
    assert result.status == ExecutionStatus.SUCCESS
    assert result.action == RecoveryAction.SWITCH_PAYMENT_PATH
    assert sub.current_mandate_id == alt_mandate.id
    assert case.status == RecoveryState.RECOVERED
    assert len(provider._attempt_ledger) == 1


def test_switch_payment_path_missing_alt_mandate_fails_closed():
    """Invariant: SWITCH_PAYMENT_PATH without valid alternate mandate fails closed."""
    customer, sub, mandate, _, case, auth, provider, now = _build_test_entities(
        action=RecoveryAction.SWITCH_PAYMENT_PATH
    )
    executor = RecoveryExecutor()

    result = executor.execute(auth, case, customer, sub, mandate, provider, now, alternative_mandate=None)

    assert result.success is False
    assert result.status == ExecutionStatus.REJECTED_PRECONDITION
    assert len(provider._attempt_ledger) == 0


def test_wait_and_retry_scheduling_does_not_debit():
    """Verify WAIT_AND_RETRY transitions state to RECOVERY_SCHEDULED with zero debit."""
    customer, sub, mandate, _, case, auth, provider, now = _build_test_entities(
        action=RecoveryAction.WAIT_AND_RETRY
    )
    executor = RecoveryExecutor()

    result = executor.execute(auth, case, customer, sub, mandate, provider, now)

    assert result.success is True
    assert result.status == ExecutionStatus.SCHEDULED
    assert case.status == RecoveryState.RECOVERY_SCHEDULED
    assert case.total_attempts == 0
    assert len(provider._attempt_ledger) == 0


def test_generate_payment_link_does_not_debit():
    """Verify GENERATE_PAYMENT_LINK creates link and records operational cost without debit."""
    customer, sub, mandate, _, case, auth, provider, now = _build_test_entities(
        action=RecoveryAction.GENERATE_PAYMENT_LINK
    )
    executor = RecoveryExecutor()

    result = executor.execute(auth, case, customer, sub, mandate, provider, now)

    assert result.success is True
    assert result.status == ExecutionStatus.LINK_GENERATED
    assert result.operational_cost_in_paisa == 100  # ₹1.00 link fee
    assert case.recovery_cost_in_paisa == 100
    assert "short_url" in result.metadata
    assert len(provider._attempt_ledger) == 0


def test_send_recovery_nudge_does_not_debit():
    """Verify SEND_RECOVERY_NUDGE increments nudge count and records cost without debit."""
    customer, sub, mandate, _, case, auth, provider, now = _build_test_entities(
        action=RecoveryAction.SEND_RECOVERY_NUDGE
    )
    executor = RecoveryExecutor()

    result = executor.execute(auth, case, customer, sub, mandate, provider, now)

    assert result.success is True
    assert result.status == ExecutionStatus.NUDGE_DISPATCHED
    assert result.operational_cost_in_paisa == 200  # ₹2.00 nudge fee
    assert case.total_nudges_sent == 1
    assert case.recovery_cost_in_paisa == 200
    assert len(provider._attempt_ledger) == 0


def test_escalate_to_human_transitions_case():
    """Verify ESCALATE_TO_HUMAN moves case to ESCALATED with concierge cost."""
    customer, sub, mandate, _, case, auth, provider, now = _build_test_entities(
        action=RecoveryAction.ESCALATE_TO_HUMAN
    )
    executor = RecoveryExecutor()

    result = executor.execute(auth, case, customer, sub, mandate, provider, now)

    assert result.success is True
    assert result.status == ExecutionStatus.ESCALATED
    assert case.status == RecoveryState.ESCALATED
    assert result.operational_cost_in_paisa == 10000  # ₹100.00 review cost
    assert case.recovery_cost_in_paisa == 10000
    assert len(provider._attempt_ledger) == 0


def test_stop_recovery_terminates_case():
    """Verify STOP_RECOVERY moves case to terminal STOPPED with zero cost."""
    customer, sub, mandate, _, case, auth, provider, now = _build_test_entities(
        action=RecoveryAction.STOP_RECOVERY
    )
    executor = RecoveryExecutor()

    result = executor.execute(auth, case, customer, sub, mandate, provider, now)

    assert result.success is True
    assert result.status == ExecutionStatus.TERMINATED
    assert case.status == RecoveryState.STOPPED
    assert len(provider._attempt_ledger) == 0


def test_provider_timeout_ambiguity_handling():
    """
    Timeout Safety: A provider gateway timeout moves case to ESCALATED for safe reconciliation
    without blindly repeating the debit.
    """
    customer, sub, mandate, _, case, auth, provider, now = _build_test_entities()
    executor = RecoveryExecutor()

    # Mock provider to return a timeout
    mock_provider = MagicMock()
    mock_provider.charge_mandate.return_value = ProviderPaymentResult(
        success=False,
        raw_error_code="GATEWAY_TIMEOUT",
        raw_error_message="Bank gateway did not respond within 30000ms",
        settled_at=now,
    )

    result = executor.execute(auth, case, customer, sub, mandate, mock_provider, now)

    assert result.success is False
    assert result.status == ExecutionStatus.AMBIGUOUS_TIMEOUT
    assert case.status == RecoveryState.ESCALATED  # Placed in review rather than blindly retried
    assert result.operational_cost_in_paisa == 500
