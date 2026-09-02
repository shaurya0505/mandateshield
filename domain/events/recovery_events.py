import uuid
from datetime import datetime, timezone
from typing import Any, Optional
from pydantic import BaseModel, Field, ConfigDict
from domain.states.recovery_state import RecoveryAction
from domain.models.payment_attempt import FailureCategory


class BaseDomainEvent(BaseModel):
    """Immutable base class for all domain events."""
    model_config = ConfigDict(frozen=True)

    event_id: str = Field(default_factory=lambda: f"evt_{uuid.uuid4().hex[:12]}")
    event_name: str
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class PaymentFailedEvent(BaseDomainEvent):
    event_name: str = "payment.failed"
    attempt_id: str
    subscription_id: str
    customer_id: str
    mandate_id: str
    amount_in_paisa: int
    raw_error_code: str
    raw_error_message: str


class RecoveryCaseOpenedEvent(BaseDomainEvent):
    event_name: str = "recovery_case.opened"
    case_id: str
    subscription_id: str
    customer_id: str
    revenue_at_risk_in_paisa: int
    failure_category: FailureCategory


class RecoveryScheduledEvent(BaseDomainEvent):
    event_name: str = "recovery_case.scheduled"
    case_id: str
    action: RecoveryAction
    scheduled_for: datetime
    reason_codes: list[str] = Field(default_factory=list)


class RecoveryAttemptedEvent(BaseDomainEvent):
    event_name: str = "recovery_case.attempted"
    case_id: str
    attempt_id: str
    action: RecoveryAction
    mandate_id: str
    amount_in_paisa: int
    attempt_number: int


class PaymentRecoveredEvent(BaseDomainEvent):
    event_name: str = "recovery_case.recovered"
    case_id: str
    subscription_id: str
    recovered_amount_in_paisa: int
    net_recovered_paisa: int
    attempts_taken: int


class RecoveryEscalatedEvent(BaseDomainEvent):
    event_name: str = "recovery_case.escalated"
    case_id: str
    reason: str
    amount_in_paisa: int


class RecoveryHaltedEvent(BaseDomainEvent):
    event_name: str = "recovery_case.halted"
    case_id: str
    rule_id: str
    reason: str


class RecoveryStoppedEvent(BaseDomainEvent):
    event_name: str = "recovery_case.stopped"
    case_id: str
    reason: str
