from typing import List, Dict, Optional
from domain.models.evaluation import (
    EvaluationPolicy,
    ScenarioOutcome,
    PolicyMetricSummary,
    LiftMetrics,
)
from domain.states.recovery_state import RecoveryAction, RecoveryState


class MetricsCalculator:
    """
    Deterministic Metrics Engine for Counterfactual Evaluation.
    Calculates gross recovery, net recovery (integer paisa), recovery rates,
    customer contact indexes, unnecessary retries, and comparative lift.
    """

    @staticmethod
    def compute_policy_summary(
        policy: EvaluationPolicy,
        outcomes: List[ScenarioOutcome],
    ) -> PolicyMetricSummary:
        eligible_cases = len(outcomes)
        if eligible_cases == 0:
            return PolicyMetricSummary(
                policy=policy,
                eligible_cases=0,
                recovered_cases=0,
                recovery_rate=0.0,
                total_revenue_at_risk_in_paisa=0,
                gross_recovered_amount_in_paisa=0,
                net_recovered_amount_in_paisa=0,
                value_weighted_recovery_rate=0.0,
                total_operational_cost_in_paisa=0,
                total_retries=0,
                total_nudges=0,
                unnecessary_retries_count=0,
                customer_contact_index=0.0,
                action_distribution={},
            )

        recovered_cases = sum(1 for o in outcomes if o.is_recovered)
        total_at_risk_in_paisa = sum(o.initial_amount_at_risk_in_paisa for o in outcomes)
        gross_recovered_in_paisa = sum(o.gross_recovered_amount_in_paisa for o in outcomes)
        total_cost_in_paisa = sum(o.operational_cost_in_paisa for o in outcomes)
        net_recovered_in_paisa = gross_recovered_in_paisa - total_cost_in_paisa

        total_retries = sum(o.total_retries for o in outcomes)
        total_nudges = sum(o.total_nudges for o in outcomes)
        unnecessary_retries = sum(o.unnecessary_retries for o in outcomes)
        escalations = sum(1 for o in outcomes if o.final_case_state == RecoveryState.ESCALATED)

        # Harassment / Customer Contact Index formulation:
        # retries * 1.0 (bank notifications/friction) + nudges * 1.5 (direct customer messages) + escalations * 0.5 (ops touch)
        contact_index = round(total_retries * 1.0 + total_nudges * 1.5 + escalations * 0.5, 2)

        recovery_rate = round(recovered_cases / eligible_cases, 4)
        value_weighted_rate = (
            round(gross_recovered_in_paisa / total_at_risk_in_paisa, 4)
            if total_at_risk_in_paisa > 0
            else 0.0
        )

        action_distribution: Dict[RecoveryAction, int] = {}
        for o in outcomes:
            for act in o.actions_taken:
                action_distribution[act] = action_distribution.get(act, 0) + 1

        return PolicyMetricSummary(
            policy=policy,
            eligible_cases=eligible_cases,
            recovered_cases=recovered_cases,
            recovery_rate=recovery_rate,
            total_revenue_at_risk_in_paisa=total_at_risk_in_paisa,
            gross_recovered_amount_in_paisa=gross_recovered_in_paisa,
            net_recovered_amount_in_paisa=net_recovered_in_paisa,
            value_weighted_recovery_rate=value_weighted_rate,
            total_operational_cost_in_paisa=total_cost_in_paisa,
            total_retries=total_retries,
            total_nudges=total_nudges,
            unnecessary_retries_count=unnecessary_retries,
            customer_contact_index=contact_index,
            action_distribution=action_distribution,
        )

    @staticmethod
    def compute_lift_metrics(
        mandateshield: PolicyMetricSummary,
        no_recovery: PolicyMetricSummary,
        fixed_retry: PolicyMetricSummary,
    ) -> LiftMetrics:
        gross_lift_vs_no = mandateshield.gross_recovered_amount_in_paisa - no_recovery.gross_recovered_amount_in_paisa
        net_lift_vs_no = mandateshield.net_recovered_amount_in_paisa - no_recovery.net_recovered_amount_in_paisa

        gross_lift_vs_fixed = mandateshield.gross_recovered_amount_in_paisa - fixed_retry.gross_recovered_amount_in_paisa
        net_lift_vs_fixed = mandateshield.net_recovered_amount_in_paisa - fixed_retry.net_recovered_amount_in_paisa

        pct_lift_vs_no = (
            round((gross_lift_vs_no / no_recovery.gross_recovered_amount_in_paisa) * 100.0, 2)
            if no_recovery.gross_recovered_amount_in_paisa > 0
            else None
        )

        pct_lift_vs_fixed = (
            round((gross_lift_vs_fixed / fixed_retry.gross_recovered_amount_in_paisa) * 100.0, 2)
            if fixed_retry.gross_recovered_amount_in_paisa > 0
            else None
        )

        rate_lift_vs_fixed = round((mandateshield.recovery_rate - fixed_retry.recovery_rate) * 100.0, 2)
        retries_avoided = max(0, fixed_retry.total_retries - mandateshield.total_retries)
        contact_reduction = round(max(0.0, fixed_retry.customer_contact_index - mandateshield.customer_contact_index), 2)

        return LiftMetrics(
            gross_recovery_lift_vs_no_recovery_in_paisa=gross_lift_vs_no,
            net_recovery_lift_vs_no_recovery_in_paisa=net_lift_vs_no,
            gross_recovery_lift_vs_fixed_retry_in_paisa=gross_lift_vs_fixed,
            net_recovery_lift_vs_fixed_retry_in_paisa=net_lift_vs_fixed,
            percentage_lift_vs_no_recovery=pct_lift_vs_no,
            percentage_lift_vs_fixed_retry=pct_lift_vs_fixed,
            recovery_rate_lift_vs_fixed_retry=rate_lift_vs_fixed,
            retries_avoided_vs_fixed_retry=retries_avoided,
            contact_reduction_vs_fixed_retry=contact_reduction,
        )
