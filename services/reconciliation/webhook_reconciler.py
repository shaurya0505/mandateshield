import uuid
import threading
from datetime import datetime, timezone
from typing import Optional, Dict

from domain.interfaces.webhook_verifier import WebhookVerifier
from domain.models.payment_attempt import PaymentAttempt, PaymentAttemptStatus
from domain.models.recovery_case import RecoveryCase
from domain.models.webhook_event import WebhookEvent, WebhookEventType, NormalizedWebhookOutcome
from domain.models.reconciliation_result import ReconciliationResult, ReconciliationStatus
from domain.states.recovery_state import RecoveryState, RecoveryStateMachine
from infrastructure.security.simulated_webhook_verifier import SimulatedWebhookVerifier


class WebhookReconciler:
    """
    Deterministic Webhook Ingestion and Reconciliation Engine.
    Settles asynchronous payment provider facts against existing PaymentAttempts and RecoveryCases.
    
    CORE INVARIANT:
        M7 executes.
        M8 reconciles.
        
    M8 must NEVER initiate payments, call RecoveryExecutor, or create StrategyProposals.
    """

    def __init__(self, verifier: Optional[WebhookVerifier] = None):
        self.verifier = verifier or SimulatedWebhookVerifier()
        # In-memory processed event registry keyed by provider_event_id
        self._processed_events: Dict[str, ReconciliationResult] = {}
        self._reconciliation_lock = threading.Lock()

    def reconcile(
        self,
        event: WebhookEvent,
        attempt: Optional[PaymentAttempt] = None,
        case: Optional[RecoveryCase] = None,
        raw_payload_bytes: Optional[bytes] = None,
        secret_key: Optional[str] = None,
    ) -> ReconciliationResult:
        """
        Deterministically verifies, deduplicates, correlates, and settles an incoming WebhookEvent.
        """
        now = datetime.now(timezone.utc)
        rec_id = f"rec_{uuid.uuid4().hex[:10]}"

        with self._reconciliation_lock:
            # -----------------------------------------------------------------
            # 1. AUTHENTICATION & SIGNATURE VERIFICATION BOUNDARY
            # -----------------------------------------------------------------
            if event.signature is not None:
                payload = raw_payload_bytes or event.event_id.encode("utf-8")
                is_valid = self.verifier.verify_signature(
                    payload_bytes=payload,
                    signature_header=event.signature,
                    secret_key=secret_key,
                )
                if not is_valid:
                    return ReconciliationResult(
                        reconciliation_id=rec_id,
                        event_id=event.event_id,
                        provider_event_id=event.provider_event_id,
                        case_id=case.id if case else None,
                        payment_attempt_id=attempt.id if attempt else None,
                        normalized_outcome=NormalizedWebhookOutcome.UNKNOWN,
                        status=ReconciliationStatus.REJECTED_VERIFICATION,
                        conflict_reason="Webhook signature/authentication verification failed.",
                        reconciled_at=now,
                    )

            # -----------------------------------------------------------------
            # 2. EVENT DEDUPLICATION BY PROVIDER_EVENT_ID
            # -----------------------------------------------------------------
            if event.provider_event_id in self._processed_events:
                prior = self._processed_events[event.provider_event_id]
                return ReconciliationResult(
                    reconciliation_id=rec_id,
                    event_id=event.event_id,
                    provider_event_id=event.provider_event_id,
                    case_id=prior.case_id,
                    payment_attempt_id=prior.payment_attempt_id,
                    previous_case_state=prior.new_case_state,
                    new_case_state=prior.new_case_state,
                    previous_attempt_status=prior.new_attempt_status,
                    new_attempt_status=prior.new_attempt_status,
                    normalized_outcome=prior.normalized_outcome,
                    status=ReconciliationStatus.DUPLICATE_IGNORED,
                    recovered_amount_in_paisa=0,  # 0 to prevent double-counting
                    incremental_cost_in_paisa=0,
                    is_duplicate=True,
                    is_ignored=True,
                    conflict_reason=f"Event '{event.provider_event_id}' was already settled.",
                    metadata={"original_reconciliation_id": prior.reconciliation_id},
                    reconciled_at=now,
                )

            # -----------------------------------------------------------------
            # 3. CORRELATION & VALIDATION CHECKS
            # -----------------------------------------------------------------
            if not attempt or not case:
                return ReconciliationResult(
                    reconciliation_id=rec_id,
                    event_id=event.event_id,
                    provider_event_id=event.provider_event_id,
                    case_id=case.id if case else None,
                    payment_attempt_id=attempt.id if attempt else None,
                    normalized_outcome=NormalizedWebhookOutcome.UNKNOWN,
                    status=ReconciliationStatus.UNRESOLVED_CORRELATION,
                    conflict_reason="PaymentAttempt or RecoveryCase not found for webhook correlation.",
                    reconciled_at=now,
                )

            # Attempt ID Correlation Check
            if event.payment_attempt_id and event.payment_attempt_id != attempt.id:
                return ReconciliationResult(
                    reconciliation_id=rec_id,
                    event_id=event.event_id,
                    provider_event_id=event.provider_event_id,
                    case_id=case.id,
                    payment_attempt_id=attempt.id,
                    normalized_outcome=NormalizedWebhookOutcome.UNKNOWN,
                    status=ReconciliationStatus.REJECTED_IDENTITY_MISMATCH,
                    conflict_reason=f"Event attempt ID '{event.payment_attempt_id}' does not match expected '{attempt.id}'.",
                    reconciled_at=now,
                )

            # Financial Amount Integrity Check
            if event.amount_in_paisa is not None and event.amount_in_paisa != attempt.amount_in_paisa:
                return ReconciliationResult(
                    reconciliation_id=rec_id,
                    event_id=event.event_id,
                    provider_event_id=event.provider_event_id,
                    case_id=case.id,
                    payment_attempt_id=attempt.id,
                    previous_case_state=case.status,
                    new_case_state=case.status,
                    previous_attempt_status=attempt.status,
                    new_attempt_status=attempt.status,
                    normalized_outcome=NormalizedWebhookOutcome.UNKNOWN,
                    status=ReconciliationStatus.REJECTED_AMOUNT_MISMATCH,
                    conflict_reason=f"Event amount (₹{event.amount_in_paisa/100:.2f}) differs from expected attempt amount (₹{attempt.amount_in_paisa/100:.2f}).",
                    reconciled_at=now,
                )

            # -----------------------------------------------------------------
            # 4. RESULT NORMALIZATION
            # -----------------------------------------------------------------
            normalized_outcome = self._normalize_event_outcome(event)
            if normalized_outcome == NormalizedWebhookOutcome.UNKNOWN:
                return ReconciliationResult(
                    reconciliation_id=rec_id,
                    event_id=event.event_id,
                    provider_event_id=event.provider_event_id,
                    case_id=case.id,
                    payment_attempt_id=attempt.id,
                    previous_case_state=case.status,
                    new_case_state=case.status,
                    previous_attempt_status=attempt.status,
                    new_attempt_status=attempt.status,
                    normalized_outcome=NormalizedWebhookOutcome.UNKNOWN,
                    status=ReconciliationStatus.UNRESOLVED_CORRELATION,
                    conflict_reason=f"Unrecognized provider status '{event.raw_status}' or event type '{event.event_type}'.",
                    reconciled_at=now,
                )

            # -----------------------------------------------------------------
            # 5. TERMINAL STATE PROTECTION & CONFLICT RESOLUTION
            # -----------------------------------------------------------------
            if RecoveryStateMachine.is_terminal(case.status):
                if case.status == RecoveryState.RECOVERED:
                    if normalized_outcome == NormalizedWebhookOutcome.SUCCESS:
                        # Case is already recovered; duplicate success is a no-op
                        result = ReconciliationResult(
                            reconciliation_id=rec_id,
                            event_id=event.event_id,
                            provider_event_id=event.provider_event_id,
                            case_id=case.id,
                            payment_attempt_id=attempt.id,
                            previous_case_state=case.status,
                            new_case_state=case.status,
                            previous_attempt_status=attempt.status,
                            new_attempt_status=attempt.status,
                            normalized_outcome=NormalizedWebhookOutcome.SUCCESS,
                            status=ReconciliationStatus.DUPLICATE_IGNORED,
                            recovered_amount_in_paisa=0,
                            is_ignored=True,
                            reconciled_at=now,
                        )
                    else:
                        # Late failure event arriving after terminal recovery must NOT regress state
                        result = ReconciliationResult(
                            reconciliation_id=rec_id,
                            event_id=event.event_id,
                            provider_event_id=event.provider_event_id,
                            case_id=case.id,
                            payment_attempt_id=attempt.id,
                            previous_case_state=case.status,
                            new_case_state=case.status,
                            previous_attempt_status=attempt.status,
                            new_attempt_status=attempt.status,
                            normalized_outcome=NormalizedWebhookOutcome.FAILURE,
                            status=ReconciliationStatus.TERMINAL_PROTECTED,
                            recovered_amount_in_paisa=0,
                            is_ignored=True,
                            conflict_reason="Late failure event ignored: case is already in terminal RECOVERED state.",
                            reconciled_at=now,
                        )
                    self._processed_events[event.provider_event_id] = result
                    return result

                elif case.status == RecoveryState.STOPPED:
                    # Stopped case cannot be reopened by webhook
                    result = ReconciliationResult(
                        reconciliation_id=rec_id,
                        event_id=event.event_id,
                        provider_event_id=event.provider_event_id,
                        case_id=case.id,
                        payment_attempt_id=attempt.id,
                        previous_case_state=case.status,
                        new_case_state=case.status,
                        previous_attempt_status=attempt.status,
                        new_attempt_status=attempt.status,
                        normalized_outcome=normalized_outcome,
                        status=ReconciliationStatus.TERMINAL_PROTECTED,
                        recovered_amount_in_paisa=0,
                        is_ignored=True,
                        conflict_reason="Webhook ignored: case is in terminal STOPPED state.",
                        reconciled_at=now,
                    )
                    self._processed_events[event.provider_event_id] = result
                    return result

            # -----------------------------------------------------------------
            # 6. ACTIVE SETTLEMENT & STATE MACHINE TRANSITION
            # -----------------------------------------------------------------
            prev_case_state = case.status
            prev_attempt_status = attempt.status

            if normalized_outcome == NormalizedWebhookOutcome.SUCCESS:
                # Settle Payment Attempt
                attempt.status = PaymentAttemptStatus.SUCCESS
                attempt.settled_at = event.event_timestamp

                # Transition case to RECOVERED and record revenue
                if case.status != RecoveryState.RECOVERED:
                    case.mark_recovered(amount_in_paisa=attempt.amount_in_paisa, recovered_at=event.event_timestamp)

                result = ReconciliationResult(
                    reconciliation_id=rec_id,
                    event_id=event.event_id,
                    provider_event_id=event.provider_event_id,
                    case_id=case.id,
                    payment_attempt_id=attempt.id,
                    previous_case_state=prev_case_state,
                    new_case_state=case.status,
                    previous_attempt_status=prev_attempt_status,
                    new_attempt_status=PaymentAttemptStatus.SUCCESS,
                    normalized_outcome=NormalizedWebhookOutcome.SUCCESS,
                    status=ReconciliationStatus.SETTLED_SUCCESS,
                    recovered_amount_in_paisa=attempt.amount_in_paisa,
                    incremental_cost_in_paisa=0,
                    reconciled_at=now,
                )
            else:
                # FAILURE Outcome
                attempt.status = PaymentAttemptStatus.FAILED
                if event.raw_error_code:
                    attempt.raw_provider_code = event.raw_error_code
                if event.raw_error_message:
                    attempt.raw_provider_message = event.raw_error_message

                # Transition case from RECOVERY_ATTEMPTED / ESCALATED to PAYMENT_FAILED
                if case.status in (RecoveryState.RECOVERY_ATTEMPTED, RecoveryState.ESCALATED):
                    case.transition_to(RecoveryState.PAYMENT_FAILED)

                result = ReconciliationResult(
                    reconciliation_id=rec_id,
                    event_id=event.event_id,
                    provider_event_id=event.provider_event_id,
                    case_id=case.id,
                    payment_attempt_id=attempt.id,
                    previous_case_state=prev_case_state,
                    new_case_state=case.status,
                    previous_attempt_status=prev_attempt_status,
                    new_attempt_status=PaymentAttemptStatus.FAILED,
                    normalized_outcome=NormalizedWebhookOutcome.FAILURE,
                    status=ReconciliationStatus.SETTLED_FAILURE,
                    recovered_amount_in_paisa=0,
                    incremental_cost_in_paisa=0,
                    reconciled_at=now,
                )

            self._processed_events[event.provider_event_id] = result
            return result

    def _normalize_event_outcome(self, event: WebhookEvent) -> NormalizedWebhookOutcome:
        """Normalizes provider status / event type into canonical domain outcomes."""
        success_types = {
            WebhookEventType.PAYMENT_CAPTURED,
            WebhookEventType.PAYMENT_AUTHORIZED,
            WebhookEventType.MANDATE_CHARGED,
        }
        success_statuses = {"captured", "charged", "success", "paid", "authorized"}

        failure_types = {
            WebhookEventType.PAYMENT_FAILED,
            WebhookEventType.MANDATE_FAILED,
        }
        failure_statuses = {"failed", "failure", "error", "cancelled", "rejected", "bounced"}

        raw_stat = event.raw_status.lower().strip()

        if event.event_type in success_types or raw_stat in success_statuses:
            return NormalizedWebhookOutcome.SUCCESS
        elif event.event_type in failure_types or raw_stat in failure_statuses:
            return NormalizedWebhookOutcome.FAILURE
        else:
            return NormalizedWebhookOutcome.UNKNOWN
