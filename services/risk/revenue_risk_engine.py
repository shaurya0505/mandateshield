from datetime import datetime, timezone
from enum import Enum
from typing import Optional, Any, Dict
from pydantic import BaseModel, Field

from domain.models.customer import Customer, CustomerRiskTier
from domain.models.mandate import Mandate, MandateStatus
from domain.models.subscription import Subscription, BillingCycle
from domain.models.payment_attempt import FailureCategory


class RecoveryPriorityLevel(str, Enum):
    """Deterministic priority classification for triage and scheduling."""
    CRITICAL = "CRITICAL"    # High-value / High-likelihood recovery required immediately
    HIGH = "HIGH"            # Standard high-value or highly recoverable failure
    MEDIUM = "MEDIUM"        # Standard priority recovery
    LOW = "LOW"              # Low value or decaying recovery likelihood
    NEGLIGIBLE = "NEGLIGIBLE"# Unrecoverable (e.g. revoked mandate, stolen instrument)


class RevenueRiskAssessment(BaseModel):
    """
    Deterministic evaluation of revenue at risk, customer priority,
    and inherent recovery potential.
    """
    subscription_id: str
    customer_id: str
    revenue_at_risk_in_paisa: int = Field(..., gt=0)
    annualized_revenue_at_risk_in_paisa: int = Field(..., gt=0)
    priority_level: RecoveryPriorityLevel
    recovery_potential_score: float = Field(..., ge=0.0, le=100.0)
    is_high_value: bool
    requires_human_escalation: bool
    explainable_factors: Dict[str, Any] = Field(default_factory=dict)
    evaluated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class RevenueRiskEngine:
    """
    Deterministic Risk & Recovery Priority Engine.
    Computes revenue-at-risk in integer paisa and calculates explainable recovery
    priority scores without LLM dependency or executing actions.
    """

    # High value threshold: ₹25,000 in paisa (Merchant policy boundary)
    HIGH_VALUE_THRESHOLD_IN_PAISA = 2500000

    # Inherent recoverability weights by failure category (0.0 to 1.0)
    CATEGORY_RECOVERABILITY_WEIGHTS: Dict[FailureCategory, float] = {
        FailureCategory.TRANSIENT_ISSUER_FAILURE: 0.95,
        FailureCategory.NETWORK_TIMEOUT: 0.90,
        FailureCategory.LIQUIDITY_FAILURE: 0.85,
        FailureCategory.RAIL_DEGRADATION: 0.75,
        FailureCategory.AUTH_FRICTION: 0.70,
        FailureCategory.PERSISTENT_FAILURE: 0.25,
        FailureCategory.UNKNOWN_FAILURE: 0.20,
        FailureCategory.MANDATE_REVOKED: 0.00,
        FailureCategory.TERMINAL_UNRECOVERABLE: 0.00,
    }

    # Attempt count decay multiplier
    ATTEMPT_DECAY_MULTIPLIERS: Dict[int, float] = {
        0: 1.0,
        1: 1.0,
        2: 0.75,
        3: 0.45,
    }

    @classmethod
    def calculate_annualized_revenue(cls, amount_in_paisa: int, cycle: BillingCycle) -> int:
        """Calculates annualized customer subscription value using integer arithmetic."""
        if cycle == BillingCycle.MONTHLY:
            return amount_in_paisa * 12
        elif cycle == BillingCycle.QUARTERLY:
            return amount_in_paisa * 4
        elif cycle == BillingCycle.ANNUAL:
            return amount_in_paisa * 1
        return amount_in_paisa * 12

    @classmethod
    def evaluate(
        cls,
        subscription: Subscription,
        customer: Customer,
        mandate: Mandate,
        failure_category: FailureCategory,
        prior_attempt_count: int = 1,
        is_rail_degraded: bool = False,
        in_historical_timing_window: bool = False,
    ) -> RevenueRiskAssessment:
        """
        Evaluates revenue at risk and assigns a deterministic priority level.
        """
        amount_in_paisa = subscription.amount_in_paisa
        annualized_paisa = cls.calculate_annualized_revenue(amount_in_paisa, subscription.billing_cycle)
        
        is_high_value = (
            amount_in_paisa >= cls.HIGH_VALUE_THRESHOLD_IN_PAISA
            or customer.risk_tier == CustomerRiskTier.VIP
        )

        # 1. Base Category Recoverability (0 - 100)
        cat_weight = cls.CATEGORY_RECOVERABILITY_WEIGHTS.get(failure_category, 0.20)
        
        # 2. Mandate Status Factor
        if mandate.status != MandateStatus.ACTIVE:
            mandate_factor = 0.0
        else:
            mandate_factor = 1.0

        # 3. Attempt Count Decay Factor
        decay_factor = cls.ATTEMPT_DECAY_MULTIPLIERS.get(prior_attempt_count, 0.15)

        # 4. Timing & Rail Boosts
        timing_bonus = 10.0 if in_historical_timing_window else 0.0
        rail_penalty = -15.0 if is_rail_degraded else 0.0

        # Compute raw recovery potential score
        raw_score = (cat_weight * mandate_factor * decay_factor * 85.0) + timing_bonus + rail_penalty
        recovery_score = max(0.0, min(100.0, round(raw_score, 2)))

        # 5. Escalate rule check: High value + previous attempt failed
        requires_escalation = (is_high_value and prior_attempt_count >= 2) or (customer.risk_tier == CustomerRiskTier.HIGH and is_high_value)

        # 6. Priority Level Classification
        if mandate_factor == 0.0 or cat_weight == 0.0:
            priority = RecoveryPriorityLevel.NEGLIGIBLE
        elif is_high_value or recovery_score >= 80.0:
            priority = RecoveryPriorityLevel.CRITICAL
        elif recovery_score >= 55.0:
            priority = RecoveryPriorityLevel.HIGH
        elif recovery_score >= 30.0:
            priority = RecoveryPriorityLevel.MEDIUM
        elif recovery_score > 0.0:
            priority = RecoveryPriorityLevel.LOW
        else:
            priority = RecoveryPriorityLevel.NEGLIGIBLE

        explainable_factors = {
            "amount_in_paisa": amount_in_paisa,
            "failure_category": failure_category.value,
            "category_weight": cat_weight,
            "mandate_status": mandate.status.value,
            "mandate_factor": mandate_factor,
            "prior_attempt_count": prior_attempt_count,
            "attempt_decay_factor": decay_factor,
            "is_rail_degraded": is_rail_degraded,
            "in_historical_timing_window": in_historical_timing_window,
            "is_high_value": is_high_value,
        }

        return RevenueRiskAssessment(
            subscription_id=subscription.id,
            customer_id=customer.id,
            revenue_at_risk_in_paisa=amount_in_paisa,
            annualized_revenue_at_risk_in_paisa=annualized_paisa,
            priority_level=priority,
            recovery_potential_score=recovery_score,
            is_high_value=is_high_value,
            requires_human_escalation=requires_escalation,
            explainable_factors=explainable_factors,
        )
