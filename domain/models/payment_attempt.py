from datetime import datetime, timezone
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class PaymentAttemptStatus(str, Enum):
    PENDING = "PENDING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"


class FailureCategory(str, Enum):
    LIQUIDITY_FAILURE = "LIQUIDITY_FAILURE"                 # e.g., Insufficient funds
    TRANSIENT_ISSUER_FAILURE = "TRANSIENT_ISSUER_FAILURE"   # e.g., Bank/Issuer technical glitch
    NETWORK_TIMEOUT = "NETWORK_TIMEOUT"                     # e.g., Gateway / Rail network timeout
    MANDATE_REVOKED = "MANDATE_REVOKED"                     # e.g., Mandate paused, expired, or cancelled
    AUTH_FRICTION = "AUTH_FRICTION"                         # e.g., 2FA/OTP failure, customer friction
    PERSISTENT_FAILURE = "PERSISTENT_FAILURE"               # e.g., Repeated consecutive failures
    RAIL_DEGRADATION = "RAIL_DEGRADATION"                   # e.g., Significant drop in rail success rate
    TERMINAL_UNRECOVERABLE = "TERMINAL_UNRECOVERABLE"       # e.g., Fraud block, stolen instrument
    UNKNOWN_FAILURE = "UNKNOWN_FAILURE"                     # Unclassified or ambiguous error


class PaymentAttempt(BaseModel):
    id: str = Field(..., description="Unique attempt ID (e.g. att_10492)")
    subscription_id: str = Field(...)
    mandate_id: str = Field(...)
    amount_in_paisa: int = Field(..., gt=0)
    attempt_number: int = Field(default=1, ge=1)
    status: PaymentAttemptStatus = Field(default=PaymentAttemptStatus.PENDING)
    raw_provider_code: Optional[str] = None
    raw_provider_message: Optional[str] = None
    normalized_category: Optional[FailureCategory] = None
    is_recovery_attempt: bool = Field(default=False)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    settled_at: Optional[datetime] = None
