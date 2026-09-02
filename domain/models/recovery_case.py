from datetime import datetime, timezone
from typing import Optional
from pydantic import BaseModel, Field
from domain.states.recovery_state import RecoveryState, RecoveryStateMachine, InvalidStateTransitionError


class RecoveryCase(BaseModel):
    """
    Core aggregate root representing an active or completed revenue recovery lifecycle.
    """
    id: str = Field(..., description="Unique recovery case identifier (e.g. case_10492)")
    subscription_id: str = Field(...)
    customer_id: str = Field(...)
    initial_attempt_id: str = Field(...)
    status: RecoveryState = Field(default=RecoveryState.PAYMENT_FAILED)
    revenue_at_risk_in_paisa: int = Field(..., gt=0, description="Amount at risk in paisa (₹1 = 100 paisa)")
    recovered_amount_in_paisa: int = Field(default=0, ge=0)
    recovery_cost_in_paisa: int = Field(default=0, ge=0)
    total_attempts: int = Field(default=0, ge=0)
    total_nudges_sent: int = Field(default=0, ge=0)
    last_attempt_at: Optional[datetime] = None
    opened_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    closed_at: Optional[datetime] = None

    def transition_to(self, new_state: RecoveryState, has_authorization: bool = False) -> None:
        """
        Transitions the recovery case to a new state after strict invariant validation.
        """
        RecoveryStateMachine.validate_transition(
            from_state=self.status,
            to_state=new_state,
            has_authorization=has_authorization
        )
        self.status = new_state
        if RecoveryStateMachine.is_terminal(new_state):
            self.closed_at = datetime.now(timezone.utc)

    def record_cost(self, cost_in_paisa: int) -> None:
        """Deterministically increments operational/recovery costs."""
        if cost_in_paisa < 0:
            raise ValueError("Cost cannot be negative.")
        self.recovery_cost_in_paisa += cost_in_paisa

    def record_attempt(self, attempt_time: Optional[datetime] = None) -> None:
        """Records an executed recovery debit attempt."""
        self.total_attempts += 1
        self.last_attempt_at = attempt_time or datetime.now(timezone.utc)

    def mark_recovered(self, amount_in_paisa: int, recovered_at: Optional[datetime] = None) -> None:
        """Marks the case as successfully recovered and seals it in terminal RECOVERED state."""
        self.recovered_amount_in_paisa = amount_in_paisa
        self.transition_to(RecoveryState.RECOVERED, has_authorization=True)
        self.closed_at = recovered_at or datetime.now(timezone.utc)

    @property
    def net_recovered_paisa(self) -> int:
        """Calculates deterministic Net Recovery in paisa."""
        return max(0, self.recovered_amount_in_paisa - self.recovery_cost_in_paisa)
