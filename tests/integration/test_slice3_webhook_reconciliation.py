from datetime import datetime, timezone
from unittest.mock import MagicMock
from domain.models.customer import Customer
from domain.models.mandate import Mandate, MandateStatus, PaymentMethod, IssuerBank
from domain.models.subscription import Subscription, BillingCycle
from domain.models.payment_attempt import PaymentAttemptStatus
from domain.models.policy_authorization import PolicyAuthorization, PolicyVerdict
from domain.models.recovery_case import RecoveryCase
from domain.models.execution_result import ExecutionStatus
from domain.models.webhook_event import WebhookEvent, WebhookEventType
from domain.models.reconciliation_result import ReconciliationStatus
from domain.states.recovery_state import RecoveryAction, RecoveryState
from domain.interfaces.payment_provider import ProviderPaymentResult
from infrastructure.security.simulated_webhook_verifier import SimulatedWebhookVerifier
from services.executor.recovery_executor import RecoveryExecutor
from services.reconciliation.webhook_reconciler import WebhookReconciler


def test_slice3_timeout_to_webhook_reconciliation_lifecycle():
    """
    Slice 3 Full Lifecycle Integration Test:
    Executor Debit -> Gateway Timeout (Ambiguity) -> Webhook Ingestion ->
    HMAC Verification -> Final Settlement -> Duplicate Delivery Idempotency.
    """
    now = datetime(2026, 9, 2, 10, 0, 0, tzinfo=timezone.utc)
    customer = Customer(id="cust_rec_int_01", name="Recon Customer", email="recon@example.com")
    mandate = Mandate(
        id="mnd_rec_int_01",
        customer_id=customer.id,
        provider_mandate_token="rzp_tok_rec_int_01",
        payment_method=PaymentMethod.CARD_MANDATE,
        issuer_bank=IssuerBank.HDFC,
        status=MandateStatus.ACTIVE,
        max_amount_in_paisa=10000000,
    )
    sub = Subscription(
        id="sub_rec_int_01",
        customer_id=customer.id,
        current_mandate_id=mandate.id,
        amount_in_paisa=799900,  # ₹7,999.00
        billing_cycle=BillingCycle.MONTHLY,
        next_billing_at=now,
    )
    case = RecoveryCase(
        id="case_rec_int_01",
        subscription_id=sub.id,
        customer_id=customer.id,
        initial_attempt_id="att_rec_init",
        revenue_at_risk_in_paisa=799900,
        status=RecoveryState.RECOVERY_ELIGIBLE,
    )
    auth = PolicyAuthorization(
        auth_id="auth_rec_int_01",
        case_id=case.id,
        decision_id="prop_rec_int_01",
        authorized_action=RecoveryAction.RETRY_NOW,
        verdict=PolicyVerdict.APPROVED,
        valid_until=now.replace(hour=23),
        execution_parameters={"amount_in_paisa": 799900},
        created_at=now,
    )

    # 1. Simulate Executor encountering a gateway timeout (e.g. socket drop)
    mock_provider = MagicMock()
    mock_provider.charge_mandate.return_value = ProviderPaymentResult(
        success=False,
        raw_error_code="GATEWAY_TIMEOUT",
        raw_error_message="504 Gateway Timeout: Bank rail did not respond in time",
        settled_at=now,
    )

    executor = RecoveryExecutor()
    exec_result = executor.execute(auth, case, customer, sub, mandate, mock_provider, now)

    # Assert executor safely handles ambiguity: case moved to ESCALATED, not blindly retried
    assert exec_result.status == ExecutionStatus.AMBIGUOUS_TIMEOUT
    assert case.status == RecoveryState.ESCALATED
    assert exec_result.payment_attempt is not None
    attempt = exec_result.payment_attempt
    assert attempt.status == PaymentAttemptStatus.FAILED

    # 2. Later, asynchronous webhook arrives confirming bank actually processed the charge
    secret = "whsec_test_secret_mandateshield_2026"
    raw_payload = b'{"event":"payment.captured","amount":799900,"id":"pay_rzp_98124"}'
    signature = SimulatedWebhookVerifier.generate_signature(raw_payload, secret)

    webhook_event = WebhookEvent(
        event_id="evt_webhook_async_01",
        provider_event_id="evt_rzp_async_98124",
        event_type=WebhookEventType.PAYMENT_CAPTURED,
        provider_payment_id="pay_rzp_98124",
        payment_attempt_id=attempt.id,
        amount_in_paisa=799900,
        raw_status="captured",
        event_timestamp=now,
        signature=f"sha256={signature}",
    )

    # 3. WebhookReconciler settles the ambiguous attempt
    reconciler = WebhookReconciler()
    recon_result = reconciler.reconcile(
        event=webhook_event,
        attempt=attempt,
        case=case,
        raw_payload_bytes=raw_payload,
        secret_key=secret,
    )

    # Verify successful reconciliation
    assert recon_result.status == ReconciliationStatus.SETTLED_SUCCESS
    assert recon_result.recovered_amount_in_paisa == 799900
    assert recon_result.incremental_cost_in_paisa == 0
    assert case.status == RecoveryState.RECOVERED
    assert case.recovered_amount_in_paisa == 799900
    assert attempt.status == PaymentAttemptStatus.SUCCESS

    # 4. Webhook re-delivery (duplicate transmission from provider)
    duplicate_result = reconciler.reconcile(
        event=webhook_event,
        attempt=attempt,
        case=case,
        raw_payload_bytes=raw_payload,
        secret_key=secret,
    )

    assert duplicate_result.status == ReconciliationStatus.DUPLICATE_IGNORED
    assert duplicate_result.is_duplicate is True
    assert duplicate_result.recovered_amount_in_paisa == 0
    # Financial state remains strictly preserved
    assert case.status == RecoveryState.RECOVERED
    assert case.recovered_amount_in_paisa == 799900
