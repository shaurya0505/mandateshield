from datetime import datetime, timezone
from enum import Enum
from typing import Optional, Dict, Any
from pydantic import BaseModel, Field, ConfigDict


class WebhookEventType(str, Enum):
    """Canonical webhook event types emitted by payment gateways / providers."""
    PAYMENT_AUTHORIZED = "payment.authorized"
    PAYMENT_CAPTURED = "payment.captured"
    PAYMENT_FAILED = "payment.failed"
    MANDATE_CHARGED = "mandate.charged"
    MANDATE_FAILED = "mandate.failed"
    REFUND_PROCESSED = "refund.processed"
    UNKNOWN = "unknown"


class NormalizedWebhookOutcome(str, Enum):
    """Normalized domain outcome from asynchronous webhook events."""
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"
    UNKNOWN = "UNKNOWN"


class WebhookEvent(BaseModel):
    """
    Immutable, strongly typed external webhook event payload.
    Represents an unforgeable factual observation from a payment provider.
    """
    model_config = ConfigDict(frozen=True)

    event_id: str = Field(..., min_length=1, description="Unique ingestion event ID (e.g. evt_9821)")
    provider_event_id: str = Field(..., min_length=1, description="Stable provider-assigned event ID (e.g. evt_rzp_8921)")
    event_type: WebhookEventType = Field(...)
    provider_payment_id: Optional[str] = Field(default=None, description="Gateway transaction/payment ID (e.g. pay_8912)")
    mandate_token: Optional[str] = Field(default=None, description="Registered mandate token associated with debit")
    payment_attempt_id: Optional[str] = Field(default=None, description="Internal PaymentAttempt ID correlation key")
    amount_in_paisa: Optional[int] = Field(default=None, ge=0, description="Transaction amount in integer paisa")
    raw_status: str = Field(..., min_length=1, description="Raw provider status string")
    raw_error_code: Optional[str] = None
    raw_error_message: Optional[str] = None
    event_timestamp: datetime = Field(..., description="Timestamp when event was created by provider")
    received_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    signature: Optional[str] = Field(default=None, description="Cryptographic webhook signature header")
    metadata: Dict[str, Any] = Field(default_factory=dict)
