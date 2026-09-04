from datetime import datetime, timezone
from enum import Enum
from typing import Optional, Any, Dict
from pydantic import BaseModel, Field, ConfigDict
from domain.states.recovery_state import RecoveryAction
from domain.models.payment_attempt import PaymentAttempt


class ExecutionStatus(str, Enum):
    """Deterministic lifecycle outcomes of a recovery execution pass."""
    SUCCESS = "SUCCESS"                            # Automated debit or recovery confirmed
    PAYMENT_FAILED = "PAYMENT_FAILED"              # Automated debit returned provider failure
    AMBIGUOUS_TIMEOUT = "AMBIGUOUS_TIMEOUT"        # Provider timeout / indeterminate state requiring reconciliation
    SCHEDULED = "SCHEDULED"                        # Future recovery attempt scheduled (WAIT_AND_RETRY)
    LINK_GENERATED = "LINK_GENERATED"              # Payment link created for customer re-authorization
    NUDGE_DISPATCHED = "NUDGE_DISPATCHED"          # Customer top-up notification dispatched
    ESCALATED = "ESCALATED"                        # Routed to human operations concierge
    TERMINATED = "TERMINATED"                      # Case closed / recovery stopped
    REJECTED_PRECONDITION = "REJECTED_PRECONDITION"# Execution rejected due to stale authorization or violated invariant
    ALREADY_CONSUMED = "ALREADY_CONSUMED"          # Idempotent replay of previously consumed authorization


class ExecutionResult(BaseModel):
    """
    Immutable, fully auditable domain record produced exclusively by RecoveryExecutor.
    """
    model_config = ConfigDict(frozen=True)

    execution_id: str = Field(..., description="Unique execution attempt ID (e.g. exec_9812)")
    auth_id: str = Field(..., description="The PolicyAuthorization ID verified before execution")
    case_id: str = Field(...)
    action: RecoveryAction
    status: ExecutionStatus
    success: bool
    amount_in_paisa: int = Field(default=0, ge=0)
    operational_cost_in_paisa: int = Field(default=0, ge=0)
    idempotency_key: str
    provider_tx_id: Optional[str] = None
    payment_attempt: Optional[PaymentAttempt] = None
    error_message: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    executed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
