from datetime import datetime, timezone
from enum import Enum
from pydantic import BaseModel, Field


class SubscriptionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAST_DUE = "PAST_DUE"
    PAUSED = "PAUSED"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"


class BillingCycle(str, Enum):
    MONTHLY = "MONTHLY"
    QUARTERLY = "QUARTERLY"
    ANNUAL = "ANNUAL"


class Subscription(BaseModel):
    id: str = Field(..., description="Unique subscription ID (e.g. sub_1029)")
    customer_id: str = Field(...)
    plan_name: str = Field(default="Standard Monthly")
    current_mandate_id: str = Field(...)
    amount_in_paisa: int = Field(..., gt=0, description="Recurring subscription amount in paisa (> 0)")
    billing_cycle: BillingCycle = Field(default=BillingCycle.MONTHLY)
    status: SubscriptionStatus = Field(default=SubscriptionStatus.ACTIVE)
    current_billing_cycle_start: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    next_billing_at: datetime = Field(...)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
