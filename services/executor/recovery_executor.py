import uuid
import threading
from datetime import datetime, timezone
from typing import Optional, Dict, Any

from domain.interfaces.payment_provider import PaymentProvider, ProviderPaymentResult
from domain.models.customer import Customer
from domain.models.mandate import Mandate, MandateStatus
from domain.models.subscription import Subscription
from domain.models.payment_attempt import PaymentAttempt, PaymentAttemptStatus, FailureCategory
from domain.models.policy_authorization import PolicyAuthorization, PolicyVerdict
from domain.models.recovery_case import RecoveryCase
from domain.models.execution_result import ExecutionResult, ExecutionStatus
from domain.states.recovery_state import RecoveryAction, RecoveryState, RecoveryStateMachine
from services.ingestion.failure_normalizer import FailureNormalizer


class RecoveryExecutor:
    """
    Deterministic Recovery Execution Engine.
    The ONLY component authorized to dispatch recovery operations against the PaymentProvider.
    
    CORE INVARIANT:
        AI proposes.
        Policy Guardian authorizes.
        Executor verifies authorization.
        Executor executes.
        
    CRITICAL:
        No valid PolicyAuthorization == NO payment execution.
    """

    # Simulated Operational Cost Matrix in integer paisa (₹1 = 100 paisa)
    COST_DEBIT_ATTEMPT_PAISA = 500       # ₹5.00 debit fee per recovery attempt
    COST_NUDGE_DISPATCH_PAISA = 200      # ₹2.00 per SMS/WhatsApp notification
    COST_PAYMENT_LINK_PAISA = 100        # ₹1.00 per recovery link generation
    COST_HUMAN_ESCALATION_PAISA = 10000  # ₹100.00 concierge review operational cost

    def __init__(self):
        # In-memory consumption and idempotency registry
        self._consumed_authorizations: Dict[str, ExecutionResult] = {}
        self._idempotency_store: Dict[str, ExecutionResult] = {}
        self._execution_lock = threading.Lock()

    def execute(
        self,
        authorization: PolicyAuthorization,
        case: RecoveryCase,
        customer: Customer,
        subscription: Subscription,
        mandate: Mandate,
        provider: PaymentProvider,
        current_time: Optional[datetime] = None,
        alternative_mandate: Optional[Mandate] = None,
    ) -> ExecutionResult:
        """
        Verifies authorization validity, enforces idempotency, validates case state,
        and dispatches the authorized action to the PaymentProvider.
        """
        now = current_time or datetime.now(timezone.utc)
        exec_id = f"exec_{uuid.uuid4().hex[:10]}"
        action = authorization.authorized_action
        idempotency_key = f"idemp_{case.id}_{authorization.auth_id}_{action.value}"

        with self._execution_lock:
            # -----------------------------------------------------------------
            # 1. IDEMPOTENCY CHECK: Return prior result if duplicate delivery
            # -----------------------------------------------------------------
            if authorization.auth_id in self._consumed_authorizations:
                prior_result = self._consumed_authorizations[authorization.auth_id]
                return ExecutionResult(
                    execution_id=exec_id,
                    auth_id=authorization.auth_id,
                    case_id=case.id,
                    action=action,
                    status=ExecutionStatus.ALREADY_CONSUMED,
                    success=prior_result.success,
                    amount_in_paisa=prior_result.amount_in_paisa,
                    operational_cost_in_paisa=0,  # 0 additional cost for duplicate call
                    idempotency_key=idempotency_key,
                    provider_tx_id=prior_result.provider_tx_id,
                    payment_attempt=prior_result.payment_attempt,
                    error_message="Duplicate execution request; returned prior execution result.",
                    metadata={"original_execution_id": prior_result.execution_id},
                    executed_at=now,
                )

            # -----------------------------------------------------------------
            # 2. MANDATORY AUTHORIZATION VERIFICATION CHECKS
            # -----------------------------------------------------------------
            # A. Approved Verdict Check
            if authorization.verdict != PolicyVerdict.APPROVED:
                return self._fail_precondition(exec_id, authorization, case, idempotency_key, now, "Authorization verdict is not APPROVED.")

            # B. Temporal Freshness / Expiration Check
            if not authorization.is_valid_for_execution(now):
                return self._fail_precondition(exec_id, authorization, case, idempotency_key, now, "PolicyAuthorization has expired.")

            # C. Entity & Case Identity Binding
            if authorization.case_id != case.id:
                return self._fail_precondition(exec_id, authorization, case, idempotency_key, now, f"Authorization case_id '{authorization.case_id}' does not match Case '{case.id}'.")

            # D. Amount Integrity Verification
            authorized_amount = authorization.execution_parameters.get("amount_in_paisa")
            if authorized_amount != subscription.amount_in_paisa:
                return self._fail_precondition(exec_id, authorization, case, idempotency_key, now, f"Authorized amount ({authorized_amount}) does not match subscription amount ({subscription.amount_in_paisa}).")

            # E. Case State Precondition Check (Terminal States Protected)
            if RecoveryStateMachine.is_terminal(case.status):
                return self._fail_precondition(exec_id, authorization, case, idempotency_key, now, f"RecoveryCase is in terminal state '{case.status.value}'. No execution allowed.")

            # -----------------------------------------------------------------
            # 3. ACTION-SPECIFIC DISPATCHING
            # -----------------------------------------------------------------
            if action == RecoveryAction.RETRY_NOW:
                return self._execute_retry_now(
                    exec_id, authorization, case, subscription, mandate, provider, idempotency_key, now
                )
            elif action == RecoveryAction.SWITCH_PAYMENT_PATH:
                return self._execute_switch_payment_path(
                    exec_id, authorization, case, subscription, alternative_mandate, provider, idempotency_key, now
                )
            elif action == RecoveryAction.WAIT_AND_RETRY:
                return self._execute_wait_and_retry(
                    exec_id, authorization, case, idempotency_key, now
                )
            elif action == RecoveryAction.GENERATE_PAYMENT_LINK:
                return self._execute_generate_payment_link(
                    exec_id, authorization, case, customer, subscription, provider, idempotency_key, now
                )
            elif action == RecoveryAction.SEND_RECOVERY_NUDGE:
                return self._execute_send_recovery_nudge(
                    exec_id, authorization, case, idempotency_key, now
                )
            elif action == RecoveryAction.ESCALATE_TO_HUMAN:
                return self._execute_escalate_to_human(
                    exec_id, authorization, case, idempotency_key, now
                )
            elif action == RecoveryAction.STOP_RECOVERY:
                return self._execute_stop_recovery(
                    exec_id, authorization, case, idempotency_key, now
                )
            else:
                return self._fail_precondition(exec_id, authorization, case, idempotency_key, now, f"Unsupported action '{action}'.")

    # ---------------------------------------------------------------------
    # ACTION IMPLEMENTATIONS
    # ---------------------------------------------------------------------

    def _execute_retry_now(
        self,
        exec_id: str,
        authorization: PolicyAuthorization,
        case: RecoveryCase,
        subscription: Subscription,
        mandate: Mandate,
        provider: PaymentProvider,
        idempotency_key: str,
        now: datetime,
    ) -> ExecutionResult:
        # Re-check mandate active status
        if mandate.status != MandateStatus.ACTIVE:
            return self._fail_precondition(exec_id, authorization, case, idempotency_key, now, f"Mandate '{mandate.id}' is '{mandate.status.value}' at execution time.")

        # In-Memory State & Invariant Transition
        case.transition_to(RecoveryState.RECOVERY_ATTEMPTED, has_authorization=True)
        case.record_attempt(attempt_time=now)
        case.record_cost(self.COST_DEBIT_ATTEMPT_PAISA)

        # Dispatch Debit to Provider
        provider_result = provider.charge_mandate(
            mandate_token=mandate.provider_mandate_token,
            amount_in_paisa=subscription.amount_in_paisa,
            idempotency_key=idempotency_key,
        )

        return self._process_debit_outcome(
            exec_id, authorization, case, subscription, mandate.id, provider_result,
            RecoveryAction.RETRY_NOW, idempotency_key, self.COST_DEBIT_ATTEMPT_PAISA, now
        )

    def _execute_switch_payment_path(
        self,
        exec_id: str,
        authorization: PolicyAuthorization,
        case: RecoveryCase,
        subscription: Subscription,
        alternative_mandate: Optional[Mandate],
        provider: PaymentProvider,
        idempotency_key: str,
        now: datetime,
    ) -> ExecutionResult:
        # Verify alternative mandate exists and is active
        if not alternative_mandate or alternative_mandate.status != MandateStatus.ACTIVE:
            return self._fail_precondition(
                exec_id, authorization, case, idempotency_key, now,
                "Authorized alternative payment method is missing or not active at execution time."
            )

        if not alternative_mandate.is_chargeable(subscription.amount_in_paisa):
            return self._fail_precondition(
                exec_id, authorization, case, idempotency_key, now,
                f"Alternative mandate max amount ({alternative_mandate.max_amount_in_paisa}) is lower than subscription amount ({subscription.amount_in_paisa})."
            )

        # In-Memory Transition
        case.transition_to(RecoveryState.RECOVERY_ATTEMPTED, has_authorization=True)
        case.record_attempt(attempt_time=now)
        case.record_cost(self.COST_DEBIT_ATTEMPT_PAISA)

        # Dispatch Debit to Alternate Mandate
        provider_result = provider.charge_mandate(
            mandate_token=alternative_mandate.provider_mandate_token,
            amount_in_paisa=subscription.amount_in_paisa,
            idempotency_key=idempotency_key,
        )

        outcome = self._process_debit_outcome(
            exec_id, authorization, case, subscription, alternative_mandate.id, provider_result,
            RecoveryAction.SWITCH_PAYMENT_PATH, idempotency_key, self.COST_DEBIT_ATTEMPT_PAISA, now
        )

        if outcome.success:
            subscription.current_mandate_id = alternative_mandate.id

        return outcome

    def _execute_wait_and_retry(
        self,
        exec_id: str,
        authorization: PolicyAuthorization,
        case: RecoveryCase,
        idempotency_key: str,
        now: datetime,
    ) -> ExecutionResult:
        # Non-debit scheduling transition
        case.transition_to(RecoveryState.RECOVERY_SCHEDULED)
        
        result = ExecutionResult(
            execution_id=exec_id,
            auth_id=authorization.auth_id,
            case_id=case.id,
            action=RecoveryAction.WAIT_AND_RETRY,
            status=ExecutionStatus.SCHEDULED,
            success=True,
            amount_in_paisa=0,
            operational_cost_in_paisa=0,
            idempotency_key=idempotency_key,
            metadata={"recommended_retry_at": authorization.execution_parameters.get("recommended_retry_at")},
            executed_at=now,
        )
        self._consumed_authorizations[authorization.auth_id] = result
        return result

    def _execute_generate_payment_link(
        self,
        exec_id: str,
        authorization: PolicyAuthorization,
        case: RecoveryCase,
        customer: Customer,
        subscription: Subscription,
        provider: PaymentProvider,
        idempotency_key: str,
        now: datetime,
    ) -> ExecutionResult:
        case.record_cost(self.COST_PAYMENT_LINK_PAISA)
        link_result = provider.generate_payment_link(
            amount_in_paisa=subscription.amount_in_paisa,
            customer_id=customer.id,
            description=f"Subscription {subscription.id} Recovery Payment Link",
        )

        result = ExecutionResult(
            execution_id=exec_id,
            auth_id=authorization.auth_id,
            case_id=case.id,
            action=RecoveryAction.GENERATE_PAYMENT_LINK,
            status=ExecutionStatus.LINK_GENERATED,
            success=True,
            amount_in_paisa=subscription.amount_in_paisa,
            operational_cost_in_paisa=self.COST_PAYMENT_LINK_PAISA,
            idempotency_key=idempotency_key,
            metadata={"link_id": link_result.link_id, "short_url": link_result.short_url},
            executed_at=now,
        )
        self._consumed_authorizations[authorization.auth_id] = result
        return result

    def _execute_send_recovery_nudge(
        self,
        exec_id: str,
        authorization: PolicyAuthorization,
        case: RecoveryCase,
        idempotency_key: str,
        now: datetime,
    ) -> ExecutionResult:
        case.total_nudges_sent += 1
        case.record_cost(self.COST_NUDGE_DISPATCH_PAISA)

        result = ExecutionResult(
            execution_id=exec_id,
            auth_id=authorization.auth_id,
            case_id=case.id,
            action=RecoveryAction.SEND_RECOVERY_NUDGE,
            status=ExecutionStatus.NUDGE_DISPATCHED,
            success=True,
            amount_in_paisa=0,
            operational_cost_in_paisa=self.COST_NUDGE_DISPATCH_PAISA,
            idempotency_key=idempotency_key,
            metadata={"nudges_sent_total": case.total_nudges_sent},
            executed_at=now,
        )
        self._consumed_authorizations[authorization.auth_id] = result
        return result

    def _execute_escalate_to_human(
        self,
        exec_id: str,
        authorization: PolicyAuthorization,
        case: RecoveryCase,
        idempotency_key: str,
        now: datetime,
    ) -> ExecutionResult:
        case.transition_to(RecoveryState.ESCALATED)
        case.record_cost(self.COST_HUMAN_ESCALATION_PAISA)

        result = ExecutionResult(
            execution_id=exec_id,
            auth_id=authorization.auth_id,
            case_id=case.id,
            action=RecoveryAction.ESCALATE_TO_HUMAN,
            status=ExecutionStatus.ESCALATED,
            success=True,
            amount_in_paisa=case.revenue_at_risk_in_paisa,
            operational_cost_in_paisa=self.COST_HUMAN_ESCALATION_PAISA,
            idempotency_key=idempotency_key,
            executed_at=now,
        )
        self._consumed_authorizations[authorization.auth_id] = result
        return result

    def _execute_stop_recovery(
        self,
        exec_id: str,
        authorization: PolicyAuthorization,
        case: RecoveryCase,
        idempotency_key: str,
        now: datetime,
    ) -> ExecutionResult:
        case.transition_to(RecoveryState.STOPPED)

        result = ExecutionResult(
            execution_id=exec_id,
            auth_id=authorization.auth_id,
            case_id=case.id,
            action=RecoveryAction.STOP_RECOVERY,
            status=ExecutionStatus.TERMINATED,
            success=True,
            amount_in_paisa=0,
            operational_cost_in_paisa=0,
            idempotency_key=idempotency_key,
            executed_at=now,
        )
        self._consumed_authorizations[authorization.auth_id] = result
        return result

    # ---------------------------------------------------------------------
    # HELPER METHODS & OUTCOME PROCESSORS
    # ---------------------------------------------------------------------

    def _process_debit_outcome(
        self,
        exec_id: str,
        authorization: PolicyAuthorization,
        case: RecoveryCase,
        subscription: Subscription,
        mandate_id: str,
        provider_result: ProviderPaymentResult,
        action: RecoveryAction,
        idempotency_key: str,
        cost_paisa: int,
        now: datetime,
    ) -> ExecutionResult:
        attempt_id = f"att_exec_{uuid.uuid4().hex[:10]}"

        if provider_result.success:
            # Succeeded -> Terminal Recovery
            case.mark_recovered(amount_in_paisa=subscription.amount_in_paisa, recovered_at=now)
            payment_attempt = PaymentAttempt(
                id=attempt_id,
                subscription_id=subscription.id,
                mandate_id=mandate_id,
                amount_in_paisa=subscription.amount_in_paisa,
                attempt_number=case.total_attempts,
                status=PaymentAttemptStatus.SUCCESS,
                is_recovery_attempt=True,
                created_at=now,
                settled_at=provider_result.settled_at,
            )
            result = ExecutionResult(
                execution_id=exec_id,
                auth_id=authorization.auth_id,
                case_id=case.id,
                action=action,
                status=ExecutionStatus.SUCCESS,
                success=True,
                amount_in_paisa=subscription.amount_in_paisa,
                operational_cost_in_paisa=cost_paisa,
                idempotency_key=idempotency_key,
                provider_tx_id=provider_result.provider_tx_id,
                payment_attempt=payment_attempt,
                executed_at=now,
            )
        else:
            # Check for ambiguous timeout
            normalized = FailureNormalizer.normalize(provider_result.raw_error_code, provider_result.raw_error_message)
            is_timeout = (normalized.category == FailureCategory.NETWORK_TIMEOUT or "timeout" in (provider_result.raw_error_code or "").lower())

            if is_timeout:
                # Ambiguous timeout: Put in ESCALATED for safe reconciliation
                case.transition_to(RecoveryState.ESCALATED)
                exec_status = ExecutionStatus.AMBIGUOUS_TIMEOUT
            else:
                case.transition_to(RecoveryState.PAYMENT_FAILED)
                exec_status = ExecutionStatus.PAYMENT_FAILED

            payment_attempt = PaymentAttempt(
                id=attempt_id,
                subscription_id=subscription.id,
                mandate_id=mandate_id,
                amount_in_paisa=subscription.amount_in_paisa,
                attempt_number=case.total_attempts,
                status=PaymentAttemptStatus.FAILED,
                raw_provider_code=provider_result.raw_error_code,
                raw_provider_message=provider_result.raw_error_message,
                normalized_category=normalized.category,
                is_recovery_attempt=True,
                created_at=now,
            )

            result = ExecutionResult(
                execution_id=exec_id,
                auth_id=authorization.auth_id,
                case_id=case.id,
                action=action,
                status=exec_status,
                success=False,
                amount_in_paisa=subscription.amount_in_paisa,
                operational_cost_in_paisa=cost_paisa,
                idempotency_key=idempotency_key,
                payment_attempt=payment_attempt,
                error_message=provider_result.raw_error_message or provider_result.raw_error_code,
                executed_at=now,
            )

        self._consumed_authorizations[authorization.auth_id] = result
        return result

    def _fail_precondition(
        self,
        exec_id: str,
        authorization: PolicyAuthorization,
        case: RecoveryCase,
        idempotency_key: str,
        now: datetime,
        reason: str,
    ) -> ExecutionResult:
        """Helper that generates a fail-closed ExecutionResult without executing a provider debit."""
        return ExecutionResult(
            execution_id=exec_id,
            auth_id=authorization.auth_id,
            case_id=case.id,
            action=authorization.authorized_action,
            status=ExecutionStatus.REJECTED_PRECONDITION,
            success=False,
            amount_in_paisa=0,
            operational_cost_in_paisa=0,
            idempotency_key=idempotency_key,
            error_message=reason,
            executed_at=now,
        )
