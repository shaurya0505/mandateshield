from datetime import datetime, timezone
from enum import Enum
from typing import Optional, Dict, Any
from pydantic import BaseModel, Field, ConfigDict
from domain.states.recovery_state import RecoveryState
from domain.models.payment_attempt import PaymentAttemptStatus
from domain.models.webhook_event import NormalizedWebhookOutcome


class ReconciliationStatus(str, Enum):
    """Deterministic settlement outcomes of an asynchronous webhook reconciliation pass."""
    SETTLED_SUCCESS = "SETTLED_SUCCESS"                    # Asynchronously confirmed and settled as successful recovery
    SETTLED_FAILURE = "SETTLED_FAILURE"                    # Asynchronously confirmed as definitive failure
    DUPLICATE_IGNORED = "DUPLICATE_IGNORED"                # Repeated delivery of previously settled event (no-op)
    CONFLICT_IGNORED = "CONFLICT_IGNORED"                  # Event contradicted higher-priority authority; safely ignored
    TERMINAL_PROTECTED = "TERMINAL_PROTECTED"              # Case is already in terminal state (RECOVERED/STOPPED); state preserved
    UNRESOLVED_CORRELATION = "UNRESOLVED_CORRELATION"      # Webhook could not be correlated to an existing PaymentAttempt
    REJECTED_VERIFICATION = "REJECTED_VERIFICATION"        # Webhook signature/authentication check failed
    REJECTED_AMOUNT_MISMATCH = "REJECTED_AMOUNT_MISMATCH"  # Webhook amount did not match expected subscription attempt amount
    REJECTED_IDENTITY_MISMATCH = "REJECTED_IDENTITY_MISMATCH" # Mandate/case identity did not match expected attempt


class ReconciliationResult(BaseModel):
    """
    Immutable, fully auditable domain record produced exclusively by WebhookReconciler.
    Records the exact before-and-after state transitions and financial impacts of reconciliation.
    """
    model_config = ConfigDict(frozen=True)

    reconciliation_id: str = Field(..., min_length=1, description="Unique reconciliation ID (e.g. rec_7129)")
    event_id: str = Field(...)
    provider_event_id: str = Field(...)
    case_id: Optional[str] = None
    payment_attempt_id: Optional[str] = None
    previous_case_state: Optional[RecoveryState] = None
    new_case_state: Optional[RecoveryState] = None
    previous_attempt_status: Optional[PaymentAttemptStatus] = None
    new_attempt_status: Optional[PaymentAttemptStatus] = None
    normalized_outcome: NormalizedWebhookOutcome
    status: ReconciliationStatus
    recovered_amount_in_paisa: int = Field(default=0, ge=0)
    incremental_cost_in_paisa: int = Field(default=0, ge=0, description="Always 0 for webhooks; no additional debit cost")
    is_duplicate: bool = False
    is_ignored: bool = False
    conflict_reason: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    reconciled_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
