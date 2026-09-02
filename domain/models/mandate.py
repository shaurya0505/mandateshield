from datetime import datetime, timezone
from enum import Enum
from pydantic import BaseModel, Field


class PaymentMethod(str, Enum):
    UPI_AUTOPAY = "UPI_AUTOPAY"
    CARD_MANDATE = "CARD_MANDATE"
    NACH = "NACH"


class IssuerBank(str, Enum):
    HDFC = "HDFC"
    ICICI = "ICICI"
    SBI = "SBI"
    AXIS = "AXIS"
    KOTAK = "KOTAK"
    YES = "YES"
    OTHER = "OTHER"


class MandateStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class Mandate(BaseModel):
    id: str = Field(..., description="Unique mandate identifier (e.g. mnd_9481)")
    customer_id: str = Field(...)
    provider_mandate_token: str = Field(..., description="Token issued by provider (e.g. mnd_tok_rzp_123)")
    payment_method: PaymentMethod
    issuer_bank: IssuerBank
    status: MandateStatus = Field(default=MandateStatus.ACTIVE)
    max_amount_in_paisa: int = Field(..., gt=0, description="Max authorization limit registered on mandate in paisa (> 0)")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def is_chargeable(self, amount_in_paisa: int) -> bool:
        """Determines if the mandate can be charged for the requested amount."""
        return self.status == MandateStatus.ACTIVE and amount_in_paisa <= self.max_amount_in_paisa
