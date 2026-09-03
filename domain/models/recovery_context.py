from datetime import datetime, timezone
from typing import List, Optional
from pydantic import BaseModel, Field, ConfigDict

from domain.models.mandate import MandateStatus, PaymentMethod, IssuerBank
from domain.models.subscription import BillingCycle
from domain.models.payment_attempt import FailureCategory
from domain.models.risk_level import RecoveryPriorityLevel
from domain.models.historical_timing_signal import HistoricalPaymentTimingSignal
from domain.models.rail_health import RailHealthMetrics


class RecoveryContext(BaseModel):
    """
    Strongly typed, immutable Recovery Context Envelope.
    Aggregates all deterministic facts, behavioral signals, mandate states,
    rail health metrics, and risk assessments prior to AI reasoning.
    
    IMPORTANT: This context contains ONLY factual & deterministically derived signals.
    It does NOT contain any preselected or assumed recovery action.
    """
    model_config = ConfigDict(frozen=True)

    # Identifiers
    recovery_case_id: str = Field(...)
    customer_id: str = Field(...)
    subscription_id: str = Field(...)
    mandate_id: str = Field(...)

    # Current Failed Payment Details
    amount_in_paisa: int = Field(..., gt=0)
    billing_cycle: BillingCycle = Field(...)
    payment_method: PaymentMethod = Field(...)
    issuer_bank: IssuerBank = Field(...)
    normalized_failure_category: FailureCategory = Field(...)
    raw_error_code: str = Field(...)
    raw_error_message: Optional[str] = None
    provenance: str = Field(...)
    failed_at: datetime = Field(...)

    # Mandate Status & Capabilities
    mandate_status: MandateStatus = Field(...)
    max_amount_in_paisa: int = Field(..., gt=0)
    is_mandate_chargeable: bool = Field(...)
    has_alternative_active_mandate: bool = Field(default=False)
    alternative_mandate_count: int = Field(default=0, ge=0)

    # Recovery Case History
    previous_attempt_count: int = Field(default=0, ge=0)
    previous_failure_categories: List[FailureCategory] = Field(default_factory=list)
    successful_recoveries_count: int = Field(default=0, ge=0)
    nudges_sent_count: int = Field(default=0, ge=0)
    last_attempt_timestamp: Optional[datetime] = None

    # Overall Subscription Payment History
    total_historical_payments: int = Field(default=0, ge=0)
    successful_payments_count: int = Field(default=0, ge=0)
    failed_payments_count: int = Field(default=0, ge=0)
    recent_successful_payment_dates: List[datetime] = Field(default_factory=list)
    recent_failed_payment_dates: List[datetime] = Field(default_factory=list)

    # Historical Payment Timing Signal (Deterministic)
    historical_timing_signal: HistoricalPaymentTimingSignal = Field(...)
    current_timestamp: datetime = Field(...)

    # Payment Rail Health
    rail_health: RailHealthMetrics = Field(...)
    is_rail_degraded: bool = Field(...)

    # Revenue Risk & Recoverability Indicators (Slice 1)
    revenue_at_risk_in_paisa: int = Field(..., gt=0)
    annualized_revenue_at_risk_in_paisa: int = Field(..., gt=0)
    priority_level: RecoveryPriorityLevel = Field(...)
    recovery_potential_score: float = Field(..., ge=0.0, le=100.0)
    is_high_value: bool = Field(...)
    requires_human_escalation: bool = Field(...)

    # Envelope Metadata
    context_created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
