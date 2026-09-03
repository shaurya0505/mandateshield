import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional
from domain.interfaces.strategy_planner import StrategyPlanner
from domain.models.mandate import MandateStatus
from domain.models.payment_attempt import FailureCategory
from domain.models.recovery_context import RecoveryContext
from domain.models.strategy_proposal import StrategyProposal, StrategyReasonCode, PlannerSource
from domain.states.recovery_state import RecoveryAction


class DeterministicFallbackPlanner(StrategyPlanner):
    """
    Deterministic rule-based recovery planner.
    Serves as an independent conservative baseline and reliable fail-safe fallback
    when LLM services are unavailable, timed out, or return malformed/invalid output.
    
    IMPORTANT: The DeterministicFallbackPlanner produces strictly ADVISORY StrategyProposal
    records with strategy_confidence=None (no fabricated numeric confidence).
    It never calls PaymentProvider, authorizes transactions, or mutates state.
    """

    def propose_strategy(
        self,
        context: RecoveryContext,
        fallback_reason: Optional[str] = None,
    ) -> StrategyProposal:
        """
        Evaluates the RecoveryContext using strict, conservative deterministic rules.
        """
        proposal_id = f"prop_fall_{uuid.uuid4().hex[:10]}"
        now = context.current_timestamp

        # Rule 1: Mandate Inactive or Revoked -> STOP_RECOVERY
        if (
            context.mandate_status != MandateStatus.ACTIVE
            or context.normalized_failure_category == FailureCategory.MANDATE_REVOKED
        ):
            return StrategyProposal(
                proposal_id=proposal_id,
                recovery_case_id=context.recovery_case_id,
                subscription_id=context.subscription_id,
                action=RecoveryAction.STOP_RECOVERY,
                reason_codes=[StrategyReasonCode.MANDATE_INACTIVE],
                rationale="Mandate is inactive or revoked. Automated debits are halted to avoid customer friction and provider fees.",
                strategy_confidence=None,
                planner_source=PlannerSource.DETERMINISTIC_FALLBACK,
                fallback_reason=fallback_reason,
                generated_at=now,
            )

        # Rule 2: Terminal Unrecoverable Error -> STOP_RECOVERY
        if context.normalized_failure_category == FailureCategory.TERMINAL_UNRECOVERABLE:
            return StrategyProposal(
                proposal_id=proposal_id,
                recovery_case_id=context.recovery_case_id,
                subscription_id=context.subscription_id,
                action=RecoveryAction.STOP_RECOVERY,
                reason_codes=[StrategyReasonCode.MANDATE_INACTIVE, StrategyReasonCode.HUMAN_REVIEW_REQUIRED],
                rationale="Terminal unrecoverable error detected (e.g. limit exceeded or account closed). Halting automated recovery.",
                strategy_confidence=None,
                planner_source=PlannerSource.DETERMINISTIC_FALLBACK,
                fallback_reason=fallback_reason,
                generated_at=now,
            )

        # Rule 3: High Value Subscription Repeated Failure -> ESCALATE_TO_HUMAN
        if context.requires_human_escalation or (context.is_high_value and context.previous_attempt_count >= 1):
            return StrategyProposal(
                proposal_id=proposal_id,
                recovery_case_id=context.recovery_case_id,
                subscription_id=context.subscription_id,
                action=RecoveryAction.ESCALATE_TO_HUMAN,
                reason_codes=[StrategyReasonCode.HIGH_VALUE_CASE, StrategyReasonCode.HUMAN_REVIEW_REQUIRED],
                rationale=f"High-value subscription (₹{context.amount_in_paisa / 100:,.2f}) with repeated failure. Route to ops concierge.",
                strategy_confidence=None,
                planner_source=PlannerSource.DETERMINISTIC_FALLBACK,
                fallback_reason=fallback_reason,
                generated_at=now,
            )

        # Rule 4: Maximum Automated Retries Approached (3+) -> ESCALATE_TO_HUMAN
        if context.previous_attempt_count >= 3:
            return StrategyProposal(
                proposal_id=proposal_id,
                recovery_case_id=context.recovery_case_id,
                subscription_id=context.subscription_id,
                action=RecoveryAction.ESCALATE_TO_HUMAN,
                reason_codes=[StrategyReasonCode.RETRY_LIMIT_APPROACHING, StrategyReasonCode.HUMAN_REVIEW_REQUIRED],
                rationale="Maximum automated retry attempts reached without settlement. Escalating for manual review.",
                strategy_confidence=None,
                planner_source=PlannerSource.DETERMINISTIC_FALLBACK,
                fallback_reason=fallback_reason,
                generated_at=now,
            )

        # Rule 5: Active Rail Degradation
        if context.is_rail_degraded:
            if context.has_alternative_active_mandate:
                return StrategyProposal(
                    proposal_id=proposal_id,
                    recovery_case_id=context.recovery_case_id,
                    subscription_id=context.subscription_id,
                    action=RecoveryAction.SWITCH_PAYMENT_PATH,
                    reason_codes=[StrategyReasonCode.RAIL_DEGRADATION, StrategyReasonCode.ACTIVE_ALTERNATIVE_MANDATE],
                    rationale=f"Primary {context.issuer_bank.value} rail is degraded, but customer has an active alternate payment method. Switch payment path.",
                    strategy_confidence=None,
                    planner_source=PlannerSource.DETERMINISTIC_FALLBACK,
                    fallback_reason=fallback_reason,
                    generated_at=now,
                )
            else:
                return StrategyProposal(
                    proposal_id=proposal_id,
                    recovery_case_id=context.recovery_case_id,
                    subscription_id=context.subscription_id,
                    action=RecoveryAction.WAIT_AND_RETRY,
                    reason_codes=[StrategyReasonCode.RAIL_DEGRADATION],
                    rationale=f"Primary {context.issuer_bank.value} rail is degraded with no alternate path. Cooldown for 4 hours before retrying.",
                    strategy_confidence=None,
                    recommended_delay_seconds=14400,
                    recommended_retry_at=now + timedelta(hours=4),
                    planner_source=PlannerSource.DETERMINISTIC_FALLBACK,
                    fallback_reason=fallback_reason,
                    generated_at=now,
                )

        # Rule 6: Liquidity Deficit (INSUFFICIENT_FUNDS)
        if context.normalized_failure_category == FailureCategory.LIQUIDITY_FAILURE:
            timing = context.historical_timing_signal
            if timing.has_timing_signal and not timing.in_current_window:
                days_until = timing.days_until_next_window or 1
                return StrategyProposal(
                    proposal_id=proposal_id,
                    recovery_case_id=context.recovery_case_id,
                    subscription_id=context.subscription_id,
                    action=RecoveryAction.WAIT_AND_RETRY,
                    reason_codes=[StrategyReasonCode.INSUFFICIENT_FUNDS, StrategyReasonCode.HISTORICAL_PAYMENT_WINDOW],
                    rationale=(
                        f"Liquidity deficit occurred outside historical payment window (days {timing.window_start_day}–{timing.window_end_day}). "
                        f"Schedule retry in {days_until} day(s) during upcoming settlement window."
                    ),
                    strategy_confidence=None,
                    recommended_delay_seconds=days_until * 86400,
                    recommended_retry_at=now + timedelta(days=days_until),
                    planner_source=PlannerSource.DETERMINISTIC_FALLBACK,
                    fallback_reason=fallback_reason,
                    generated_at=now,
                )
            else:
                return StrategyProposal(
                    proposal_id=proposal_id,
                    recovery_case_id=context.recovery_case_id,
                    subscription_id=context.subscription_id,
                    action=RecoveryAction.SEND_RECOVERY_NUDGE,
                    reason_codes=[StrategyReasonCode.INSUFFICIENT_FUNDS, StrategyReasonCode.INSUFFICIENT_HISTORY],
                    rationale="Liquidity deficit without distinct future timing window. Dispatch customer top-up notification.",
                    strategy_confidence=None,
                    planner_source=PlannerSource.DETERMINISTIC_FALLBACK,
                    fallback_reason=fallback_reason,
                    generated_at=now,
                )

        # Rule 7: Transient Provider Error / Network Timeout
        if context.normalized_failure_category in (FailureCategory.TRANSIENT_ISSUER_FAILURE, FailureCategory.NETWORK_TIMEOUT):
            if context.previous_attempt_count == 0:
                return StrategyProposal(
                    proposal_id=proposal_id,
                    recovery_case_id=context.recovery_case_id,
                    subscription_id=context.subscription_id,
                    action=RecoveryAction.RETRY_NOW,
                    reason_codes=[StrategyReasonCode.TRANSIENT_PROVIDER_FAILURE],
                    rationale="Transient bank/network glitch on healthy active mandate. Immediate retry recommended.",
                    strategy_confidence=None,
                    planner_source=PlannerSource.DETERMINISTIC_FALLBACK,
                    fallback_reason=fallback_reason,
                    generated_at=now,
                )
            else:
                return StrategyProposal(
                    proposal_id=proposal_id,
                    recovery_case_id=context.recovery_case_id,
                    subscription_id=context.subscription_id,
                    action=RecoveryAction.WAIT_AND_RETRY,
                    reason_codes=[StrategyReasonCode.TRANSIENT_PROVIDER_FAILURE],
                    rationale="Repeated transient failure. Cooldown 30 minutes before re-attempting.",
                    strategy_confidence=None,
                    recommended_delay_seconds=1800,
                    recommended_retry_at=now + timedelta(minutes=30),
                    planner_source=PlannerSource.DETERMINISTIC_FALLBACK,
                    fallback_reason=fallback_reason,
                    generated_at=now,
                )

        # Rule 8: Authentication Friction
        if context.normalized_failure_category == FailureCategory.AUTH_FRICTION:
            return StrategyProposal(
                proposal_id=proposal_id,
                recovery_case_id=context.recovery_case_id,
                subscription_id=context.subscription_id,
                action=RecoveryAction.GENERATE_PAYMENT_LINK,
                reason_codes=[StrategyReasonCode.UNKNOWN_FAILURE],
                rationale="Authentication friction detected. Generate payment link for direct customer re-authorization.",
                strategy_confidence=None,
                planner_source=PlannerSource.DETERMINISTIC_FALLBACK,
                fallback_reason=fallback_reason,
                generated_at=now,
            )

        # Rule 9: Default / Unknown Failure -> ESCALATE_TO_HUMAN
        return StrategyProposal(
            proposal_id=proposal_id,
            recovery_case_id=context.recovery_case_id,
            subscription_id=context.subscription_id,
            action=RecoveryAction.ESCALATE_TO_HUMAN,
            reason_codes=[StrategyReasonCode.UNKNOWN_FAILURE, StrategyReasonCode.HUMAN_REVIEW_REQUIRED],
            rationale="Unclassified or ambiguous error code. Route to human operator for safety.",
            strategy_confidence=None,
            planner_source=PlannerSource.DETERMINISTIC_FALLBACK,
            fallback_reason=fallback_reason,
            generated_at=now,
        )
