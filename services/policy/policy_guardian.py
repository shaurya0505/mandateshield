import uuid
from datetime import datetime, timedelta, timezone
from typing import List, Optional
from domain.models.mandate import MandateStatus
from domain.models.policy_authorization import PolicyAuthorization, PolicyVerdict
from domain.models.recovery_context import RecoveryContext
from domain.models.strategy_proposal import StrategyProposal
from domain.policies.policy_config import PolicyConfig
from domain.policies.policy_evaluation import PolicyEvaluation
from domain.policies.rule_types import EvaluatedRuleResult, RuleCategory
from domain.states.recovery_state import RecoveryAction, RecoveryState, RecoveryStateMachine


class PolicyGuardian:
    """
    Deterministic Safety & Authorization Gateway.
    The mandatory final authority that evaluates AI strategy proposals against explicit
    financial, provider, regulatory, merchant, and state-machine invariants.
    
    CORE PRINCIPLE:
        AI proposes.
        Policy Guardian authorizes.
        Executor executes.
    """

    def __init__(self, config: Optional[PolicyConfig] = None):
        self.config = config or PolicyConfig()

    def evaluate(
        self,
        context: RecoveryContext,
        proposal: StrategyProposal,
        case_status: Optional[RecoveryState] = None,
    ) -> PolicyEvaluation:
        """
        Deterministically evaluates a StrategyProposal against all safety rules.
        Fails closed on any violation or unexpected error.
        """
        eval_id = f"eval_{uuid.uuid4().hex[:10]}"
        now = context.current_timestamp
        evaluated_rules: List[EvaluatedRuleResult] = []
        rejection_reasons: List[str] = []
        is_escalation_required = False

        try:
            # -------------------------------------------------------------
            # RULE 1: Action Space Enum Validity (SIMULATION_POLICY)
            # -------------------------------------------------------------
            action_is_valid = isinstance(proposal.action, RecoveryAction)
            rule_sim_01 = EvaluatedRuleResult(
                rule_id="RULE-SIM-01",
                rule_name="Action Enum Space Validity",
                category=RuleCategory.SIMULATION_POLICY,
                passed=action_is_valid,
                description="Proposed action must belong strictly to the bounded RecoveryAction domain enum.",
                details={"proposed_action": str(proposal.action)},
            )
            evaluated_rules.append(rule_sim_01)
            if not action_is_valid:
                rejection_reasons.append("Invalid or unknown recovery action.")

            # -------------------------------------------------------------
            # RULE 2: Recovery Case State Machine Check (MERCHANT_POLICY)
            # -------------------------------------------------------------
            current_state = case_status or RecoveryState.RECOVERY_ELIGIBLE
            is_terminal = RecoveryStateMachine.is_terminal(current_state)
            state_passed = not is_terminal
            rule_state_01 = EvaluatedRuleResult(
                rule_id="RULE-STATE-01",
                rule_name="Active Recovery State Check",
                category=RuleCategory.MERCHANT_POLICY,
                passed=state_passed,
                description="Recovery actions can only be authorized for active cases; terminal cases are locked.",
                details={"case_state": current_state.value, "is_terminal": is_terminal},
            )
            evaluated_rules.append(rule_state_01)
            if not state_passed:
                rejection_reasons.append(f"Case is in terminal state '{current_state.value}'. No recovery allowed.")

            # -------------------------------------------------------------
            # RULE 3: Mandate Status & Chargeability (PROVIDER_RULE)
            # -------------------------------------------------------------
            # Direct debit actions require active mandate
            is_debit_action = proposal.action in (RecoveryAction.RETRY_NOW, RecoveryAction.SWITCH_PAYMENT_PATH)
            if is_debit_action and proposal.action == RecoveryAction.RETRY_NOW:
                mandate_passed = (context.mandate_status == MandateStatus.ACTIVE)
            else:
                mandate_passed = True  # Switch path checks alternate mandate; non-debit actions allow inactive

            rule_prov_01 = EvaluatedRuleResult(
                rule_id="RULE-PROV-01",
                rule_name="Mandate Active Status Check",
                category=RuleCategory.PROVIDER_RULE,
                passed=mandate_passed,
                description="Mandate must be ACTIVE in provider records to execute automated debits.",
                details={"mandate_status": context.mandate_status.value, "action": proposal.action.value},
            )
            evaluated_rules.append(rule_prov_01)
            if not mandate_passed:
                rejection_reasons.append(f"Mandate status is '{context.mandate_status.value}'. Automated debit prohibited.")

            # -------------------------------------------------------------
            # RULE 4: Mandate Maximum Amount Limit (PROVIDER_RULE)
            # -------------------------------------------------------------
            amount_passed = (context.amount_in_paisa <= context.max_amount_in_paisa)
            rule_prov_02 = EvaluatedRuleResult(
                rule_id="RULE-PROV-02",
                rule_name="Mandate Registered Amount Cap",
                category=RuleCategory.PROVIDER_RULE,
                passed=amount_passed,
                description="Debit amount cannot exceed the mandate's registered authorization limit.",
                details={
                    "amount_in_paisa": context.amount_in_paisa,
                    "max_amount_in_paisa": context.max_amount_in_paisa,
                },
            )
            evaluated_rules.append(rule_prov_02)
            if not amount_passed:
                rejection_reasons.append(
                    f"Amount ₹{context.amount_in_paisa/100:,.2f} exceeds mandate max limit ₹{context.max_amount_in_paisa/100:,.2f}."
                )

            # -------------------------------------------------------------
            # RULE 5: Maximum Automated Retries Limit (MERCHANT_POLICY)
            # -------------------------------------------------------------
            if proposal.action == RecoveryAction.RETRY_NOW:
                retry_count_passed = (context.previous_attempt_count < self.config.max_retry_attempts)
            else:
                retry_count_passed = True

            rule_merch_01 = EvaluatedRuleResult(
                rule_id="RULE-MERCH-01",
                rule_name="Maximum Automated Retry Threshold",
                category=RuleCategory.MERCHANT_POLICY,
                passed=retry_count_passed,
                description=f"Maximum {self.config.max_retry_attempts} automated retries permitted per billing cycle.",
                details={
                    "previous_attempts": context.previous_attempt_count,
                    "max_allowed": self.config.max_retry_attempts,
                },
            )
            evaluated_rules.append(rule_merch_01)
            if not retry_count_passed:
                rejection_reasons.append(
                    f"Maximum retry threshold ({self.config.max_retry_attempts}) reached. Further automated retries blocked."
                )

            # -------------------------------------------------------------
            # RULE 6: Minimum Retry Cooldown Period (MERCHANT_POLICY)
            # -------------------------------------------------------------
            if proposal.action == RecoveryAction.RETRY_NOW and context.previous_attempt_count > 0 and context.last_attempt_timestamp:
                elapsed_sec = (context.current_timestamp - context.last_attempt_timestamp).total_seconds()
                cooldown_passed = (elapsed_sec >= self.config.retry_cooldown_seconds)
                cooldown_details = {
                    "elapsed_seconds": int(elapsed_sec),
                    "required_cooldown_seconds": self.config.retry_cooldown_seconds,
                }
            else:
                cooldown_passed = True
                cooldown_details = {"cooldown_applicable": False}

            rule_merch_02 = EvaluatedRuleResult(
                rule_id="RULE-MERCH-02",
                rule_name="Automated Retry Cooldown Enforcement",
                category=RuleCategory.MERCHANT_POLICY,
                passed=cooldown_passed,
                description=f"Minimum {self.config.retry_cooldown_seconds//3600}h cooldown required between debit retries.",
                details=cooldown_details,
            )
            evaluated_rules.append(rule_merch_02)
            if not cooldown_passed:
                rejection_reasons.append("Retry cooldown period has not elapsed since previous attempt.")

            # -------------------------------------------------------------
            # RULE 7: High-Value VIP Transaction Escalation Boundary (MERCHANT_POLICY)
            # -------------------------------------------------------------
            is_high_val = (context.amount_in_paisa >= self.config.high_value_threshold_in_paisa or context.is_high_value)
            if (
                is_high_val
                and self.config.high_value_requires_escalation_on_repeat
                and context.previous_attempt_count >= 1
                and is_debit_action
            ):
                high_val_passed = False
                is_escalation_required = True
            else:
                high_val_passed = True

            rule_merch_03 = EvaluatedRuleResult(
                rule_id="RULE-MERCH-03",
                rule_name="High-Value VIP Escalation Boundary",
                category=RuleCategory.MERCHANT_POLICY,
                passed=high_val_passed,
                description=f"High-value subscriptions (> ₹{self.config.high_value_threshold_in_paisa/100:,.2f}) must escalate on repeat failure.",
                details={
                    "is_high_value": is_high_val,
                    "previous_attempts": context.previous_attempt_count,
                },
            )
            evaluated_rules.append(rule_merch_03)
            if not high_val_passed:
                rejection_reasons.append("High-value transaction repeat failure requires human concierge escalation.")

            # -------------------------------------------------------------
            # RULE 8: Customer Contact / Nudge Limit (MERCHANT_POLICY)
            # -------------------------------------------------------------
            if proposal.action == RecoveryAction.SEND_RECOVERY_NUDGE:
                nudge_passed = (context.nudges_sent_count < self.config.max_notifications)
            else:
                nudge_passed = True

            rule_merch_04 = EvaluatedRuleResult(
                rule_id="RULE-MERCH-04",
                rule_name="Customer Notification Rate Limit",
                category=RuleCategory.MERCHANT_POLICY,
                passed=nudge_passed,
                description=f"Maximum {self.config.max_notifications} notifications permitted to prevent customer fatigue.",
                details={
                    "nudges_sent": context.nudges_sent_count,
                    "max_allowed": self.config.max_notifications,
                },
            )
            evaluated_rules.append(rule_merch_04)
            if not nudge_passed:
                rejection_reasons.append(
                    f"Customer notification limit ({self.config.max_notifications}) exceeded. Further nudges blocked."
                )

            # -------------------------------------------------------------
            # RULE 9: Alternative Mandate Availability for Path Switching (MERCHANT_POLICY)
            # -------------------------------------------------------------
            if proposal.action == RecoveryAction.SWITCH_PAYMENT_PATH:
                alt_mandate_passed = (
                    context.has_alternative_active_mandate
                    and context.alternative_mandate_count > 0
                )
            else:
                alt_mandate_passed = True

            rule_merch_05 = EvaluatedRuleResult(
                rule_id="RULE-MERCH-05",
                rule_name="Alternative Payment Method Verification",
                category=RuleCategory.MERCHANT_POLICY,
                passed=alt_mandate_passed,
                description="Switching payment paths requires a verified active alternative payment method on file.",
                details={
                    "has_alternative_active_mandate": context.has_alternative_active_mandate,
                    "alternative_mandate_count": context.alternative_mandate_count,
                },
            )
            evaluated_rules.append(rule_merch_05)
            if not alt_mandate_passed:
                rejection_reasons.append("Customer has no verified active alternative payment method available.")

            # -------------------------------------------------------------
            # VERDICT DETERMINATION
            # -------------------------------------------------------------
            all_passed = all(r.passed for r in evaluated_rules)

            if all_passed:
                verdict = PolicyVerdict.APPROVED
                is_approved = True
                authorization = PolicyAuthorization(
                    auth_id=f"auth_{uuid.uuid4().hex[:10]}",
                    case_id=context.recovery_case_id,
                    decision_id=proposal.proposal_id,
                    authorized_action=proposal.action,
                    verdict=PolicyVerdict.APPROVED,
                    evaluated_rules=evaluated_rules,
                    rejection_reasons=[],
                    valid_until=now + timedelta(seconds=self.config.authorization_validity_seconds),
                    execution_parameters={
                        "amount_in_paisa": context.amount_in_paisa,
                        "recommended_delay_seconds": proposal.recommended_delay_seconds,
                        "recommended_retry_at": proposal.recommended_retry_at.isoformat() if proposal.recommended_retry_at else None,
                    },
                    created_at=now,
                )
            else:
                is_approved = False
                authorization = None
                if is_escalation_required or proposal.action == RecoveryAction.ESCALATE_TO_HUMAN:
                    verdict = PolicyVerdict.ESCALATED
                else:
                    verdict = PolicyVerdict.REJECTED

            return PolicyEvaluation(
                evaluation_id=eval_id,
                recovery_case_id=context.recovery_case_id,
                proposal_id=proposal.proposal_id,
                evaluated_action=proposal.action,
                verdict=verdict,
                is_approved=is_approved,
                evaluated_rules=evaluated_rules,
                rejection_reasons=rejection_reasons,
                evaluated_at=now,
                authorization=authorization,
            )

        except Exception as err:
            # FAIL-CLOSED SAFETY NET
            return PolicyEvaluation(
                evaluation_id=eval_id,
                recovery_case_id=context.recovery_case_id,
                proposal_id=proposal.proposal_id,
                evaluated_action=proposal.action,
                verdict=PolicyVerdict.REJECTED,
                is_approved=False,
                evaluated_rules=evaluated_rules,
                rejection_reasons=[f"Unexpected policy evaluation error: {str(err)[:100]}"],
                evaluated_at=now,
                authorization=None,
            )
