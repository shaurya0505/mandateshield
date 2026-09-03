from pydantic import BaseModel, Field
from domain.models.mandate import IssuerBank, PaymentMethod


class RailHealthMetrics(BaseModel):
    """Statistical health summary for a specific payment rail."""
    issuer_bank: IssuerBank
    payment_method: PaymentMethod
    sample_window_minutes: int
    total_attempts: int
    successful_attempts: int
    success_rate: float = Field(..., ge=0.0, le=1.0)
    is_degraded: bool
