from datetime import datetime, timezone
from typing import List, Optional
from domain.models.customer import Customer
from domain.models.mandate import Mandate, MandateStatus
from domain.models.subscription import Subscription
from domain.models.payment_attempt import PaymentAttempt, PaymentAttemptStatus, FailureCategory
from domain.models.recovery_case import RecoveryCase
from domain.models.recovery_context import RecoveryContext
from domain.interfaces.payment_provider import RailHealthMetrics
from services.ingestion.failure_normalizer import NormalizedFailure
from services.risk.revenue_risk_engine import RevenueRiskAssessment
from services.signals.historical_timing_extractor import HistoricalTimingExtractor


class RecoveryContextBuilder:
    """
    Factory service that constructs an immutable RecoveryContext envelope
    by aggregating factual signals from all Slice 1 domain and service components.
    """

    @classmethod
    def build(
        cls,
        recovery_case: RecoveryCase,
        customer: Customer,
        subscription: Subscription,
        mandate: Mandate,
        normalized_failure: NormalizedFailure,
        risk_assessment: RevenueRiskAssessment,
        rail_health: RailHealthMetrics,
        customer_mandates: Optional[List[Mandate]] = None,
        payment_attempt_history: Optional[List[PaymentAttempt]] = None,
        historical_successful_dates: Optional[List[datetime]] = None,
        historical_failed_dates: Optional[List[datetime]] = None,
        current_time: Optional[datetime] = None,
    ) -> RecoveryContext:
        """
        Builds a complete, immutable RecoveryContext.
        """
        now = current_time or datetime.now(timezone.utc)
        history = payment_attempt_history or []
        success_dates = historical_successful_dates or []
        failed_dates = historical_failed_dates or []
        all_mandates = customer_mandates or [mandate]

        # 1. Deterministic Timing Signal Extraction
        timing_signal = HistoricalTimingExtractor.extract(
            successful_payment_timestamps=success_dates,
            current_time=now,
        )

        # 2. Alternative Mandate Availability Check
        alternative_active_mandates = [
            m for m in all_mandates
            if m.id != mandate.id
            and m.status == MandateStatus.ACTIVE
            and m.is_chargeable(subscription.amount_in_paisa)
        ]
        has_alt_mandate = len(alternative_active_mandates) > 0
        alt_mandate_count = len(alternative_active_mandates)

        # 3. Prior Attempt & Failure Category Aggregation
        prior_categories: List[FailureCategory] = [
            att.normalized_category
            for att in history
            if att.normalized_category is not None and att.status == PaymentAttemptStatus.FAILED
        ]

        # 4. Assemble Immutable Context
        return RecoveryContext(
            # Identifiers
            recovery_case_id=recovery_case.id,
            customer_id=customer.id,
            subscription_id=subscription.id,
            mandate_id=mandate.id,

            # Current Payment & Failure
            amount_in_paisa=subscription.amount_in_paisa,
            billing_cycle=subscription.billing_cycle,
            payment_method=mandate.payment_method,
            issuer_bank=mandate.issuer_bank,
            normalized_failure_category=normalized_failure.category,
            raw_error_code=normalized_failure.raw_error_code,
            raw_error_message=normalized_failure.raw_error_message,
            provenance=normalized_failure.provenance,
            failed_at=normalized_failure.normalized_at,

            # Mandate Status
            mandate_status=mandate.status,
            max_amount_in_paisa=mandate.max_amount_in_paisa,
            is_mandate_chargeable=mandate.is_chargeable(subscription.amount_in_paisa),
            has_alternative_active_mandate=has_alt_mandate,
            alternative_mandate_count=alt_mandate_count,

            # Recovery History
            previous_attempt_count=recovery_case.total_attempts,
            previous_failure_categories=prior_categories,
            successful_recoveries_count=1 if recovery_case.recovered_amount_in_paisa > 0 else 0,
            nudges_sent_count=recovery_case.total_nudges_sent,
            last_attempt_timestamp=recovery_case.last_attempt_at,

            # Payment History
            total_historical_payments=len(success_dates) + len(failed_dates),
            successful_payments_count=len(success_dates),
            failed_payments_count=len(failed_dates),
            recent_successful_payment_dates=success_dates,
            recent_failed_payment_dates=failed_dates,

            # Timing Signal
            historical_timing_signal=timing_signal,
            current_timestamp=now,

            # Rail Health
            rail_health=rail_health,
            is_rail_degraded=rail_health.is_degraded,

            # Risk Assessment
            revenue_at_risk_in_paisa=risk_assessment.revenue_at_risk_in_paisa,
            annualized_revenue_at_risk_in_paisa=risk_assessment.annualized_revenue_at_risk_in_paisa,
            priority_level=risk_assessment.priority_level,
            recovery_potential_score=risk_assessment.recovery_potential_score,
            is_high_value=risk_assessment.is_high_value,
            requires_human_escalation=risk_assessment.requires_human_escalation,
            context_created_at=now,
        )
