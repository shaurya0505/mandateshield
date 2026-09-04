from datetime import datetime, timezone
import pytest

from domain.models.customer import Customer
from domain.models.mandate import Mandate, MandateStatus, PaymentMethod, IssuerBank
from domain.models.subscription import Subscription, BillingCycle
from domain.models.payment_attempt import PaymentAttempt, PaymentAttemptStatus, FailureCategory
from domain.models.recovery_case import RecoveryCase
from domain.models.webhook_event import WebhookEvent, WebhookEventType, NormalizedWebhookOutcome
from domain.models.reconciliation_result import ReconciliationStatus
from domain.states.recovery_state import RecoveryState
from infrastructure.security.simulated_webhook_verifier import SimulatedWebhookVerifier
from services.reconciliation.webhook_reconciler import WebhookReconciler


def _build_test_entities(
    amount_in_paisa: int = 499900,
    case_status: RecoveryState = RecoveryState.RECOVERY_ATTEMPTED,
    attempt_status: PaymentAttemptStatus = PaymentAttemptStatus.FAILED,
):
    now = datetime(2026, 9, 2, 10, 0, 0, tzinfo=timezone.utc)
    customer = Customer(id="cust_rec_01", name="Rec Customer", email="rec@example.com")
    mandate = Mandate(
        id="mnd_rec_01",
        customer_id=customer.id,
        provider_mandate_token="rzp_tok_rec_01",
        payment_method=PaymentMethod.CARD_MANDATE,
        issuer_bank=IssuerBank.HDFC,
        status=MandateStatus.ACTIVE,
        max_amount_in_paisa=10000000,
    )
    sub = Subscription(
        id="sub_rec_01",
        customer_id=customer.id,
        current_mandate_id=mandate.id,
        amount_in_paisa=amount_in_paisa,
        billing_cycle=BillingCycle.MONTHLY,
        next_billing_at=now,
    )
    case = RecoveryCase(
        id="case_rec_01",
        subscription_id=sub.id,
        customer_id=customer.id,
        initial_attempt_id="att_rec_01",
        revenue_at_risk_in_paisa=amount_in_paisa,
        status=case_status,
        total_attempts=1,
    )
    attempt = PaymentAttempt(
        id="att_rec_01",
        subscription_id=sub.id,
        mandate_id=mandate.id,
        amount_in_paisa=amount_in_paisa,
        attempt_number=1,
        status=attempt_status,
        is_recovery_attempt=True,
        created_at=now,
    )
    return customer, sub, mandate, case, attempt, now


def test_valid_webhook_success_settles_case_to_recovered():
    """Verify valid payment.captured webhook settles attempt and marks case RECOVERED."""
    _, _, _, case, attempt, now = _build_test_entities()
    reconciler = WebhookReconciler()

    event = WebhookEvent(
        event_id="evt_01",
        provider_event_id="evt_rzp_1001",
        event_type=WebhookEventType.PAYMENT_CAPTURED,
        provider_payment_id="pay_9921",
        payment_attempt_id=attempt.id,
        amount_in_paisa=499900,
        raw_status="captured",
        event_timestamp=now,
        signature="valid_mock_signature",
    )

    result = reconciler.reconcile(event, attempt=attempt, case=case)

    assert result.status == ReconciliationStatus.SETTLED_SUCCESS
    assert result.normalized_outcome == NormalizedWebhookOutcome.SUCCESS
    assert result.recovered_amount_in_paisa == 499900
    assert result.incremental_cost_in_paisa == 0
    assert attempt.status == PaymentAttemptStatus.SUCCESS
    assert case.status == RecoveryState.RECOVERED
    assert case.recovered_amount_in_paisa == 499900


def test_invalid_signature_fails_closed():
    """Invariant: Unverified webhook signature is rejected; ZERO state mutations occur."""
    _, _, _, case, attempt, now = _build_test_entities()
    reconciler = WebhookReconciler()

    event = WebhookEvent(
        event_id="evt_02",
        provider_event_id="evt_rzp_1002",
        event_type=WebhookEventType.PAYMENT_CAPTURED,
        payment_attempt_id=attempt.id,
        amount_in_paisa=499900,
        raw_status="captured",
        event_timestamp=now,
        signature="invalid_signature",
    )

    result = reconciler.reconcile(event, attempt=attempt, case=case)

    assert result.status == ReconciliationStatus.REJECTED_VERIFICATION
    assert case.status == RecoveryState.RECOVERY_ATTEMPTED  # Case state unchanged
    assert case.recovered_amount_in_paisa == 0


def test_cryptographic_hmac_signature_verification():
    """Verify real HMAC-SHA256 signature verification."""
    _, _, _, case, attempt, now = _build_test_entities()
    secret = "whsec_test_secret_mandateshield_2026"
    raw_payload = b'{"event":"payment.captured","id":"pay_101"}'
    valid_sig = SimulatedWebhookVerifier.generate_signature(raw_payload, secret)

    reconciler = WebhookReconciler()
    event = WebhookEvent(
        event_id="evt_03",
        provider_event_id="evt_rzp_1003",
        event_type=WebhookEventType.PAYMENT_CAPTURED,
        payment_attempt_id=attempt.id,
        amount_in_paisa=499900,
        raw_status="captured",
        event_timestamp=now,
        signature=f"sha256={valid_sig}",
    )

    result = reconciler.reconcile(event, attempt=attempt, case=case, raw_payload_bytes=raw_payload, secret_key=secret)
    assert result.status == ReconciliationStatus.SETTLED_SUCCESS


def test_event_deduplication_ignores_duplicate_delivery():
    """Invariant: Duplicate delivery of same provider event ID is ignored and does not double-count revenue."""
    _, _, _, case, attempt, now = _build_test_entities()
    reconciler = WebhookReconciler()

    event = WebhookEvent(
        event_id="evt_04",
        provider_event_id="evt_rzp_1004",
        event_type=WebhookEventType.PAYMENT_CAPTURED,
        payment_attempt_id=attempt.id,
        amount_in_paisa=499900,
        raw_status="captured",
        event_timestamp=now,
        signature="valid_mock_signature",
    )

    # First delivery
    res1 = reconciler.reconcile(event, attempt=attempt, case=case)
    assert res1.status == ReconciliationStatus.SETTLED_SUCCESS
    assert case.recovered_amount_in_paisa == 499900

    # Duplicate delivery
    res2 = reconciler.reconcile(event, attempt=attempt, case=case)
    assert res2.status == ReconciliationStatus.DUPLICATE_IGNORED
    assert res2.is_duplicate is True
    assert res2.recovered_amount_in_paisa == 0
    # Crucial financial invariant: revenue count is NOT doubled
    assert case.recovered_amount_in_paisa == 499900


def test_amount_mismatch_rejected():
    """Invariant: Webhook amount differing from expected attempt amount is rejected."""
    _, _, _, case, attempt, now = _build_test_entities(amount_in_paisa=499900)
    reconciler = WebhookReconciler()

    # Webhook claims ₹1,000 instead of ₹4,999
    event = WebhookEvent(
        event_id="evt_05",
        provider_event_id="evt_rzp_1005",
        event_type=WebhookEventType.PAYMENT_CAPTURED,
        payment_attempt_id=attempt.id,
        amount_in_paisa=100000,
        raw_status="captured",
        event_timestamp=now,
        signature="valid_mock_signature",
    )

    result = reconciler.reconcile(event, attempt=attempt, case=case)

    assert result.status == ReconciliationStatus.REJECTED_AMOUNT_MISMATCH
    assert case.status == RecoveryState.RECOVERY_ATTEMPTED
    assert case.recovered_amount_in_paisa == 0


def test_unresolved_correlation_when_attempt_missing():
    """Invariant: Webhook that cannot be mapped to an attempt fails closed."""
    reconciler = WebhookReconciler()
    now = datetime(2026, 9, 2, 10, 0, 0, tzinfo=timezone.utc)

    event = WebhookEvent(
        event_id="evt_06",
        provider_event_id="evt_rzp_1006",
        event_type=WebhookEventType.PAYMENT_CAPTURED,
        payment_attempt_id="att_unknown_999",
        amount_in_paisa=499900,
        raw_status="captured",
        event_timestamp=now,
        signature="valid_mock_signature",
    )

    result = reconciler.reconcile(event, attempt=None, case=None)

    assert result.status == ReconciliationStatus.UNRESOLVED_CORRELATION
    assert "not found" in result.conflict_reason


def test_ambiguous_timeout_settled_by_success_webhook():
    """
    Timeout Settlement: Case in ESCALATED due to M7 timeout is settled to RECOVERED upon webhook SUCCESS.
    """
    _, _, _, case, attempt, now = _build_test_entities(
        case_status=RecoveryState.ESCALATED,
        attempt_status=PaymentAttemptStatus.FAILED,
    )
    reconciler = WebhookReconciler()

    event = WebhookEvent(
        event_id="evt_07",
        provider_event_id="evt_rzp_1007",
        event_type=WebhookEventType.PAYMENT_CAPTURED,
        payment_attempt_id=attempt.id,
        amount_in_paisa=499900,
        raw_status="captured",
        event_timestamp=now,
        signature="valid_mock_signature",
    )

    result = reconciler.reconcile(event, attempt=attempt, case=case)

    assert result.status == ReconciliationStatus.SETTLED_SUCCESS
    assert case.status == RecoveryState.RECOVERED
    assert attempt.status == PaymentAttemptStatus.SUCCESS
    assert case.recovered_amount_in_paisa == 499900


def test_ambiguous_timeout_settled_by_failure_webhook():
    """
    Timeout Settlement: Case in ESCALATED due to M7 timeout is settled to PAYMENT_FAILED upon webhook FAILURE.
    """
    _, _, _, case, attempt, now = _build_test_entities(
        case_status=RecoveryState.ESCALATED,
        attempt_status=PaymentAttemptStatus.FAILED,
    )
    reconciler = WebhookReconciler()

    event = WebhookEvent(
        event_id="evt_08",
        provider_event_id="evt_rzp_1008",
        event_type=WebhookEventType.PAYMENT_FAILED,
        payment_attempt_id=attempt.id,
        amount_in_paisa=499900,
        raw_status="failed",
        raw_error_code="INSUFFICIENT_FUNDS",
        raw_error_message="Account balance deficit",
        event_timestamp=now,
        signature="valid_mock_signature",
    )

    result = reconciler.reconcile(event, attempt=attempt, case=case)

    assert result.status == ReconciliationStatus.SETTLED_FAILURE
    assert case.status == RecoveryState.PAYMENT_FAILED
    assert attempt.status == PaymentAttemptStatus.FAILED
    assert case.recovered_amount_in_paisa == 0


def test_terminal_recovered_protected_from_late_failure():
    """
    Terminal Protection: A late failure webhook arriving after case is already RECOVERED
    is ignored and cannot regress the terminal state.
    """
    _, _, _, case, attempt, now = _build_test_entities(
        case_status=RecoveryState.RECOVERED,
        attempt_status=PaymentAttemptStatus.SUCCESS,
    )
    case.recovered_amount_in_paisa = 499900
    reconciler = WebhookReconciler()

    late_failure_event = WebhookEvent(
        event_id="evt_09",
        provider_event_id="evt_rzp_1009",
        event_type=WebhookEventType.PAYMENT_FAILED,
        payment_attempt_id=attempt.id,
        amount_in_paisa=499900,
        raw_status="failed",
        event_timestamp=now,
        signature="valid_mock_signature",
    )

    result = reconciler.reconcile(late_failure_event, attempt=attempt, case=case)

    assert result.status == ReconciliationStatus.TERMINAL_PROTECTED
    assert result.is_ignored is True
    assert case.status == RecoveryState.RECOVERED  # Invariant: Terminal state does not regress
    assert case.recovered_amount_in_paisa == 499900


def test_terminal_stopped_protected_from_reopening():
    """
    Terminal Protection: A webhook arriving for a STOPPED case is ignored and cannot reopen recovery.
    """
    _, _, _, case, attempt, now = _build_test_entities(case_status=RecoveryState.STOPPED)
    reconciler = WebhookReconciler()

    event = WebhookEvent(
        event_id="evt_10",
        provider_event_id="evt_rzp_1010",
        event_type=WebhookEventType.PAYMENT_CAPTURED,
        payment_attempt_id=attempt.id,
        amount_in_paisa=499900,
        raw_status="captured",
        event_timestamp=now,
        signature="valid_mock_signature",
    )

    result = reconciler.reconcile(event, attempt=attempt, case=case)

    assert result.status == ReconciliationStatus.TERMINAL_PROTECTED
    assert result.is_ignored is True
    assert case.status == RecoveryState.STOPPED


def test_unknown_provider_status_fails_closed():
    """Invariant: Webhook with unmapped or unknown provider status fails closed."""
    _, _, _, case, attempt, now = _build_test_entities()
    reconciler = WebhookReconciler()

    event = WebhookEvent(
        event_id="evt_11",
        provider_event_id="evt_rzp_1011",
        event_type=WebhookEventType.UNKNOWN,
        payment_attempt_id=attempt.id,
        amount_in_paisa=499900,
        raw_status="some_undocumented_vendor_status",
        event_timestamp=now,
        signature="valid_mock_signature",
    )

    result = reconciler.reconcile(event, attempt=attempt, case=case)

    assert result.status == ReconciliationStatus.UNRESOLVED_CORRELATION
    assert case.status == RecoveryState.RECOVERY_ATTEMPTED
