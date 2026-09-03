import json
from typing import Any, Dict
from domain.models.recovery_context import RecoveryContext


class ContextSerializer:
    """
    Serializes a RecoveryContext into a clean, sanitized JSON envelope for LLM reasoning.
    Guarantees that internal database objects, secrets, and raw infrastructure handles
    are never transmitted to external AI endpoints.
    """

    @classmethod
    def serialize_for_ai(cls, context: RecoveryContext) -> str:
        """Produces a sanitized, structured JSON string representing the RecoveryContext."""
        payload: Dict[str, Any] = {
            "case_id": context.recovery_case_id,
            "subscription_id": context.subscription_id,
            "amount_in_inr": round(context.amount_in_paisa / 100, 2),
            "amount_in_paisa": context.amount_in_paisa,
            "billing_cycle": context.billing_cycle.value,
            "payment_method": context.payment_method.value,
            "issuer_bank": context.issuer_bank.value,
            "failure_category": context.normalized_failure_category.value,
            "raw_error_code": context.raw_error_code,
            "mandate_status": context.mandate_status.value,
            "is_mandate_chargeable": context.is_mandate_chargeable,
            "has_alternative_active_mandate": context.has_alternative_active_mandate,
            "alternative_mandate_count": context.alternative_mandate_count,
            "previous_attempt_count": context.previous_attempt_count,
            "successful_recoveries_count": context.successful_recoveries_count,
            "nudges_sent_count": context.nudges_sent_count,
            "current_simulation_time": context.current_timestamp.isoformat(),
            "historical_timing_signal": {
                "has_timing_signal": context.historical_timing_signal.has_timing_signal,
                "window_start_day": context.historical_timing_signal.window_start_day,
                "window_end_day": context.historical_timing_signal.window_end_day,
                "sample_size": context.historical_timing_signal.sample_size,
                "matching_observations": context.historical_timing_signal.matching_observations,
                "support_ratio": context.historical_timing_signal.support_ratio,
                "confidence_score": context.historical_timing_signal.confidence_score,
                "in_current_window": context.historical_timing_signal.in_current_window,
                "days_until_next_window": context.historical_timing_signal.days_until_next_window,
                "explanation": context.historical_timing_signal.explanation,
            },
            "rail_health": {
                "issuer_bank": context.rail_health.issuer_bank.value,
                "payment_method": context.rail_health.payment_method.value,
                "success_rate": context.rail_health.success_rate,
                "is_degraded": context.rail_health.is_degraded,
            },
            "risk_assessment": {
                "priority_level": context.priority_level.value,
                "recovery_potential_score": context.recovery_potential_score,
                "is_high_value": context.is_high_value,
                "requires_human_escalation": context.requires_human_escalation,
            },
        }
        return json.dumps(payload, indent=2)
