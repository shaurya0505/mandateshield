from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional, Any
from pydantic import BaseModel, Field
from domain.models.mandate import MandateStatus, PaymentMethod, IssuerBank
from domain.models.rail_health import RailHealthMetrics


class ProviderPaymentResult(BaseModel):
    """Normalized response from a payment provider attempt."""
    success: bool
    provider_tx_id: Optional[str] = None
    raw_error_code: Optional[str] = None
    raw_error_message: Optional[str] = None
    settled_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)


class ProviderPaymentLinkResult(BaseModel):
    """Normalized response from payment link creation."""
    link_id: str
    short_url: str
    status: str = "active"
    expires_at: datetime


class ProviderMandateStatusResult(BaseModel):
    """Normalized mandate verification response."""
    mandate_token: str
    status: MandateStatus
    max_amount_in_paisa: int
    is_active: bool


class PaymentProvider(ABC):
    """
    Core interface for payment operations.
    Allows transparent switching between SimulatedPaymentProvider and RazorpayTestProvider.
    """

    @abstractmethod
    def charge_mandate(
        self,
        mandate_token: str,
        amount_in_paisa: int,
        idempotency_key: str,
        attempt_context: Optional[dict[str, Any]] = None,
    ) -> ProviderPaymentResult:
        """Attempts an automated recurring debit against a registered mandate token."""
        pass

    @abstractmethod
    def generate_payment_link(
        self,
        amount_in_paisa: int,
        customer_id: str,
        description: str,
        expires_in_seconds: int = 86400,
    ) -> ProviderPaymentLinkResult:
        """Generates a dynamic payment link for alternate recovery."""
        pass

    @abstractmethod
    def verify_mandate(self, mandate_token: str) -> ProviderMandateStatusResult:
        """Queries the provider to verify current mandate status."""
        pass

    @abstractmethod
    def get_rail_health(
        self,
        issuer_bank: IssuerBank,
        payment_method: PaymentMethod,
        window_minutes: int = 60,
    ) -> RailHealthMetrics:
        """Computes statistical success rate and degradation state for an issuer/method rail."""
        pass
