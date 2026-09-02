from datetime import datetime, timezone
from enum import Enum
from pydantic import BaseModel, Field, ConfigDict


class CustomerRiskTier(str, Enum):
    LOW = "LOW"
    STANDARD = "STANDARD"
    HIGH = "HIGH"
    VIP = "VIP"


class Customer(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str = Field(..., description="Unique customer ID (e.g. cust_1029)")
    name: str = Field(..., min_length=1)
    email: str = Field(..., min_length=3)
    phone: str = Field(default="+919876543210")
    risk_tier: CustomerRiskTier = Field(default=CustomerRiskTier.STANDARD)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
