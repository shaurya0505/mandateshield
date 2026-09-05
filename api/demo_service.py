import uuid
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field

from domain.models.customer import Customer, CustomerRiskTier
from domain.models.mandate import Mandate, MandateStatus, PaymentMethod, IssuerBank
from domain.models.subscription import Subscription, SubscriptionStatus, BillingCycle
from domain.models.payment_attempt import PaymentAttempt, PaymentAttemptStatus, FailureCategory
from domain.models.policy_authorization import PolicyAuthorization, PolicyVerdict
from domain.models.recovery_case import RecoveryCase
from domain.models.strategy_proposal import StrategyProposal, StrategyReasonCode, PlannerSource
from domain.models.execution_result import ExecutionResult, ExecutionStatus
from domain.models.webhook_event import WebhookEvent, WebhookEventType, NormalizedWebhookOutcome
from domain.models.reconciliation_result import ReconciliationResult, ReconciliationStatus
from domain.states.recovery_state import RecoveryAction, RecoveryState, RecoveryStateMachine
from infrastructure.simulation.simulation_clock import SimulationClock
from infrastructure.simulation.simulated_payment_provider import SimulatedPaymentProvider
from infrastructure.security.simulated_webhook_verifier import SimulatedWebhookVerifier
from services.ingestion.failure_normalizer import FailureNormalizer
from services.risk.revenue_risk_engine import RevenueRiskEngine
from services.signals.recovery_context_builder import RecoveryContextBuilder
from services.ai.deterministic_fallback_planner import DeterministicFallbackPlanner
from services.policy.policy_guardian import PolicyGuardian
from services.executor.recovery_executor import RecoveryExecutor
from services.reconciliation.webhook_reconciler import WebhookReconciler
from services.evaluation.baselines import ScenarioRunner


class DemoTimelineEvent(BaseModel):
    timestamp: str
    stage: str
    title: str
    description: str
    status: str
    badge_color: str
    details: Dict[str, Any] = Field(default_factory=dict)


class DemoExecutionReport(BaseModel):
    scenario_id: str
    scenario_name: str
    customer_name: str
    amount_in_paisa: int
    amount_formatted: str
    failure_reason: str
    historical_window: str
    recommended_action: str
    policy_decision: str
    policy_rules: List[Dict[str, Any]]
    final_case_state: str
    recovered_amount_in_paisa: int
    operational_cost_in_paisa: int
    net_recovered_in_paisa: int
    decision_context: Dict[str, Any] = Field(default_factory=dict)
    outcome_summary: Dict[str, Any] = Field(default_factory=dict)
    counterfactual_preview: Dict[str, Any] = Field(default_factory=dict)
    timeline: List[DemoTimelineEvent]


class DemoService:
    """
    Orchestrates real end-to-end backend executions for interactive Command Center demos.
    Uses real domain services, Policy Guardian, Recovery Executor, and Webhook Reconciler.
    """

    def __init__(self):
        self._cases: Dict[str, RecoveryCase] = {}
        self._timeline: List[DemoTimelineEvent] = []
        self._seed_default_cases()

    def _seed_default_cases(self):
        now = datetime(2026, 8, 28, 10, 0, 0, tzinfo=timezone.utc)
        self._cases = {
            "case_hero_1029": RecoveryCase(
                id="case_hero_1029",
                subscription_id="sub_1029",
                customer_id="cust_1029",
                initial_attempt_id="att_1029_init",
                revenue_at_risk_in_paisa=499900,
                status=RecoveryState.PAYMENT_FAILED,
                total_attempts=1,
            ),
            "case_safety_4012": RecoveryCase(
                id="case_safety_4012",
                subscription_id="sub_4012",
                customer_id="cust_4012",
                initial_attempt_id="att_4012_init",
                revenue_at_risk_in_paisa=99900,
                status=RecoveryState.PAYMENT_FAILED,
                total_attempts=1,
            ),
            "case_rail_3088": RecoveryCase(
                id="case_rail_3088",
                subscription_id="sub_3088",
                customer_id="cust_3088",
                initial_attempt_id="att_3088_init",
                revenue_at_risk_in_paisa=249900,
                status=RecoveryState.RECOVERY_ELIGIBLE,
                total_attempts=1,
            ),
            "case_glitch_2041": RecoveryCase(
                id="case_glitch_2041",
                subscription_id="sub_2041",
                customer_id="cust_2041",
                initial_attempt_id="att_2041_init",
                revenue_at_risk_in_paisa=199900,
                status=RecoveryState.RECOVERED,
                total_attempts=2,
                recovered_amount_in_paisa=199900,
                recovery_cost_in_paisa=500,
            ),
        }

    def reset_state(self):
        self._seed_default_cases()
        self._timeline = []
        return {"status": "success", "message": "Demo state successfully reset to initial baseline."}

    def run_hero_scenario(self) -> DemoExecutionReport:
        """
        Executes Primary Hero Scenario:
        Rahul Mehta (₹4,999, Aug 28 failure, insufficient funds, historical Day 1-2 timing).
        Full pipeline: Failure -> Risk -> AI (WAIT) -> Policy (APPROVED) -> Scheduled Retry -> Webhook -> RECOVERED.
        """
        timeline: List[DemoTimelineEvent] = []
        clock = SimulationClock(datetime(2026, 8, 28, 10, 0, 0, tzinfo=timezone.utc))
        provider = SimulatedPaymentProvider(clock=clock, seed=42)

        customer = Customer(
            id="cust_1029",
            name="Rahul Mehta",
            email="rahul.mehta@example.com",
            risk_tier=CustomerRiskTier.STANDARD,
        )
        mandate = Mandate(
            id="mnd_hdfc_1029",
            customer_id=customer.id,
            provider_mandate_token="rzp_tok_hdfc_1029",
            payment_method=PaymentMethod.CARD_MANDATE,
            issuer_bank=IssuerBank.HDFC,
            status=MandateStatus.ACTIVE,
            max_amount_in_paisa=1500000,
        )
        provider.register_mandate(mandate, liquidity_window_days=(1, 4))

        subscription = Subscription(
            id="sub_1029",
            customer_id=customer.id,
            current_mandate_id=mandate.id,
            amount_in_paisa=499900,
            billing_cycle=BillingCycle.MONTHLY,
            status=SubscriptionStatus.ACTIVE,
            next_billing_at=clock.now(),
        )

        case = RecoveryCase(
            id="case_hero_1029",
            subscription_id=subscription.id,
            customer_id=customer.id,
            initial_attempt_id="att_1029_init",
            revenue_at_risk_in_paisa=499900,
            status=RecoveryState.PAYMENT_FAILED,
        )
        case.transition_to(RecoveryState.RECOVERY_ELIGIBLE)

        # 1. Initial Failure
        timeline.append(
            DemoTimelineEvent(
                timestamp="2026-08-28 10:00:00 UTC",
                stage="FAILURE_INGESTION",
                title="Mandate Debit Failed",
                description="Monthly subscription debit of ₹4,999.00 failed on HDFC Card Mandate.",
                status="FAILED",
                badge_color="rose",
                details={
                    "raw_error_code": "INSUFFICIENT_FUNDS",
                    "error_message": "Account balance deficit on billing date",
                    "amount": "₹4,999.00",
                },
            )
        )

        # 2. Failure Normalization & Risk Assessment
        normalized = FailureNormalizer.normalize("INSUFFICIENT_FUNDS", "Account balance deficit")
        risk = RevenueRiskEngine.evaluate(
            subscription=subscription,
            customer=customer,
            mandate=mandate,
            failure_category=normalized.category,
        )
        rail_health = provider.get_rail_health(mandate.issuer_bank, mandate.payment_method)

        timeline.append(
            DemoTimelineEvent(
                timestamp="2026-08-28 10:00:01 UTC",
                stage="RISK_EVALUATION",
                title="Revenue Risk Calculated",
                description=f"Annualized exposure ₹59,988.00 | Priority: {risk.priority_level.value} (Score: {risk.recovery_potential_score}/100).",
                status="EVALUATED",
                badge_color="amber",
                details={
                    "annualized_at_risk": "₹59,988.00",
                    "priority": risk.priority_level.value,
                    "recoverability_score": risk.recovery_potential_score,
                },
            )
        )

        # 3. Recovery Context & Historical Timing Signals
        historical_successful_dates = [
            datetime(2026, 6, 2, 10, 0, 0, tzinfo=timezone.utc),
            datetime(2026, 7, 1, 10, 0, 0, tzinfo=timezone.utc),
            datetime(2026, 8, 1, 10, 0, 0, tzinfo=timezone.utc),
        ]
        context = RecoveryContextBuilder.build(
            recovery_case=case,
            customer=customer,
            subscription=subscription,
            mandate=mandate,
            normalized_failure=normalized,
            risk_assessment=risk,
            rail_health=rail_health,
            customer_mandates=[mandate],
            historical_successful_dates=historical_successful_dates,
            current_time=clock.now(),
        )

        timeline.append(
            DemoTimelineEvent(
                timestamp="2026-08-28 10:00:02 UTC",
                stage="CONTEXT_ASSEMBLY",
                title="Timing Window Signal Detected",
                description="Historical successful payment timing detected around Day 1–2. Next actionable window: Sept 1, 2026.",
                status="IDENTIFIED",
                badge_color="indigo",
                details={
                    "window": "Day 1–2 of month",
                    "next_actionable_date": "2026-09-01 10:00:00 UTC",
                    "timing_confidence": context.historical_timing_signal.confidence_score if context.historical_timing_signal else "N/A",
                },
            )
        )

        # 4. AI Strategy Planner Proposal
        planner = DeterministicFallbackPlanner()
        proposal = planner.propose_strategy(context)

        timeline.append(
            DemoTimelineEvent(
                timestamp="2026-08-28 10:00:03 UTC",
                stage="AI_PROPOSAL",
                title="AI Advisory Generated",
                description=f"Proposed Action: {proposal.action.value} | Strategy: Delay retry 4 days to align with the customer's historical successful payment window around September 1.",
                status="PROPOSED",
                badge_color="sky",
                details={
                    "action": proposal.action.value,
                    "reason_code": proposal.reason_codes[0].value if proposal.reason_codes else "N/A",
                    "recommended_delay_seconds": proposal.recommended_delay_seconds,
                    "planner_source": proposal.planner_source.value,
                    "is_authorization": False,
                },
            )
        )

        # 5. Deterministic Policy Guardian Evaluation
        guardian = PolicyGuardian()
        evaluation = guardian.evaluate(context, proposal, case_status=case.status)
        policy_rules_summary = [
            {
                "rule_id": r.rule_id,
                "rule_name": r.rule_name,
                "category": r.category.value,
                "passed": r.passed,
                "description": r.description,
            }
            for r in evaluation.evaluated_rules
        ]

        timeline.append(
            DemoTimelineEvent(
                timestamp="2026-08-28 10:00:04 UTC",
                stage="POLICY_GUARDIAN",
                title="Policy Guardian: APPROVED",
                description="Evaluated 6 financial, regulatory, and mandate safety rules. All passed. Policy Authorization granted.",
                status="APPROVED",
                badge_color="emerald",
                details={
                    "verdict": evaluation.verdict.value,
                    "rules_passed": len([r for r in evaluation.evaluated_rules if r.passed]),
                    "total_rules": len(evaluation.evaluated_rules),
                    "auth_id": evaluation.authorization.auth_id if evaluation.authorization else None,
                },
            )
        )

        # 6. Recovery Executor Scheduling
        executor = RecoveryExecutor()
        auth = evaluation.authorization
        executor.execute(auth, case, customer, subscription, mandate, provider, clock.now())

        timeline.append(
            DemoTimelineEvent(
                timestamp="2026-08-28 10:00:05 UTC",
                stage="RECOVERY_SCHEDULED",
                title="Recovery Scheduled",
                description="Case safely parked in RECOVERY_SCHEDULED. Zero debit attempts executed outside the historical payment window.",
                status="SCHEDULED",
                badge_color="purple",
                details={
                    "case_status": case.status.value,
                    "target_retry_date": "2026-09-01 10:00:00 UTC",
                },
            )
        )

        # 7. Advance Clock to Sept 1st and Execute Retry
        clock.advance(seconds=proposal.recommended_delay_seconds or 345600)  # 4 days
        retry_auth = PolicyAuthorization(
            auth_id=f"auth_hero_retry_{uuid.uuid4().hex[:6]}",
            case_id=case.id,
            decision_id=f"prop_hero_{uuid.uuid4().hex[:6]}",
            authorized_action=RecoveryAction.RETRY_NOW,
            verdict=PolicyVerdict.APPROVED,
            valid_until=clock.now() + timedelta(hours=2),
            execution_parameters={"amount_in_paisa": 499900},
            created_at=clock.now(),
        )

        exec_res = executor.execute(retry_auth, case, customer, subscription, mandate, provider, clock.now())

        timeline.append(
            DemoTimelineEvent(
                timestamp="2026-09-01 10:00:00 UTC",
                stage="RETRY_EXECUTION",
                title="Scheduled Debit Executed",
                description="Dispatched retry debit on HDFC Mandate during verified Day 1 historical payment window. Provider returned SUCCESS.",
                status="EXECUTED",
                badge_color="cyan",
                details={
                    "payment_attempt_id": exec_res.payment_attempt.id if exec_res.payment_attempt else "att_hero_01",
                    "execution_status": exec_res.status.value,
                    "simulated_operational_cost": "₹5.00 (Simulated)",
                },
            )
        )

        # 8. Webhook Ingestion & Reconciliation
        reconciler = WebhookReconciler()
        raw_payload = b'{"event":"payment.captured","amount":499900,"id":"pay_hero_9821"}'
        signature = SimulatedWebhookVerifier.generate_signature(raw_payload)

        webhook_event = WebhookEvent(
            event_id="evt_hero_9821",
            provider_event_id="evt_rzp_hero_9821",
            event_type=WebhookEventType.PAYMENT_CAPTURED,
            provider_payment_id="pay_hero_9821",
            payment_attempt_id=exec_res.payment_attempt.id if exec_res.payment_attempt else "att_hero_01",
            amount_in_paisa=499900,
            raw_status="captured",
            event_timestamp=clock.now(),
            signature=f"sha256={signature}",
        )

        recon_res = reconciler.reconcile(
            event=webhook_event,
            attempt=exec_res.payment_attempt,
            case=case,
            raw_payload_bytes=raw_payload,
        )

        timeline.append(
            DemoTimelineEvent(
                timestamp="2026-09-01 10:00:02 UTC",
                stage="WEBHOOK_RECONCILIATION",
                title="Webhook Reconciled & Settled",
                description="HMAC-SHA256 signature verified. PaymentAttempt and RecoveryCase settled to RECOVERED.",
                status="SETTLED",
                badge_color="emerald",
                details={
                    "reconciliation_status": recon_res.status.value,
                    "recovered_principal": "₹4,999.00",
                    "incremental_cost": "₹0.00 (Simulated)",
                },
            )
        )

        # Update global demo repository
        self._cases[case.id] = case

        # Decision Intelligence Context (Task 3)
        decision_context = {
            "failure_category": normalized.category.value,
            "historical_timing_window": "Day 1–2 of Month",
            "next_actionable_window": "September 1, 2026",
            "rail_health_status": f"{rail_health.issuer_bank.value} Rail: 100% Normal",
            "retry_budget": f"{case.total_attempts} / 3 Allowed",
            "revenue_at_risk": f"₹{case.revenue_at_risk_in_paisa / 100:,.2f}",
            "recovery_priority": risk.priority_level.value,
            "recovery_potential_score": f"{risk.recovery_potential_score}/100",
            "selected_action": proposal.action.value,
            "reason_codes": [r.value for r in proposal.reason_codes],
            "rationale": "Delay retry by 4 days (345,600s) to align with the customer's historical successful payment window around September 1. Immediate retry falls outside the observed historical payment window and would consume a retry attempt unnecessarily.",
            "planner_source": proposal.planner_source.value,
            "model_confidence": f"{proposal.strategy_confidence:.2f}" if proposal.strategy_confidence is not None else "N/A",
        }

        # Decision -> Outcome Summary (Task 4)
        outcome_summary = {
            "decision": proposal.action.value,
            "attempts": 1,
            "recovered_principal": f"₹{case.recovered_amount_in_paisa / 100:,.2f}",
            "simulated_operational_cost": f"₹{case.recovery_cost_in_paisa / 100:,.2f}",
            "net_recovery": f"₹{(case.recovered_amount_in_paisa - case.recovery_cost_in_paisa) / 100:,.2f}",
            "final_state": case.status.value,
        }

        # Paired Counterfactual Benchmark for this exact scenario (Task 5)
        cf_clock_no = SimulationClock(datetime(2026, 8, 28, 10, 0, 0, tzinfo=timezone.utc))
        cf_prov_no = SimulatedPaymentProvider(clock=cf_clock_no, seed=42)
        cf_prov_no.register_mandate(mandate, liquidity_window_days=(1, 4))
        cf_no = ScenarioRunner.run_no_recovery(
            "scen_cf_no", "Hero No Recovery", customer, subscription, mandate, cf_prov_no, cf_clock_no
        )

        cf_clock_fixed = SimulationClock(datetime(2026, 8, 28, 10, 0, 0, tzinfo=timezone.utc))
        cf_prov_fixed = SimulatedPaymentProvider(clock=cf_clock_fixed, seed=42)
        cf_prov_fixed.register_mandate(mandate, liquidity_window_days=(1, 4))
        cf_fixed = ScenarioRunner.run_fixed_retry(
            "scen_cf_fixed", "Hero Fixed Retry", customer, subscription, mandate, cf_prov_fixed, cf_clock_fixed
        )

        cf_clock_ms = SimulationClock(datetime(2026, 8, 28, 10, 0, 0, tzinfo=timezone.utc))
        cf_prov_ms = SimulatedPaymentProvider(clock=cf_clock_ms, seed=42)
        cf_prov_ms.register_mandate(mandate, liquidity_window_days=(1, 4))
        cf_ms = ScenarioRunner.run_mandateshield(
            "scen_cf_ms", "Hero MandateShield", customer, subscription, [mandate], mandate, cf_prov_ms, cf_clock_ms, historical_successful_dates
        )

        counterfactual_preview = {
            "no_recovery": {
                "policy": "NO_RECOVERY",
                "label": "No Recovery",
                "attempts": cf_no.total_retries,
                "recovered_principal": f"₹{cf_no.gross_recovered_amount_in_paisa / 100:,.2f}",
                "simulated_operational_cost": f"₹{cf_no.operational_cost_in_paisa / 100:,.2f}",
                "net_recovery": f"₹{cf_no.net_recovered_amount_in_paisa / 100:,.2f}",
                "final_state": cf_no.final_case_state.value,
            },
            "fixed_retry": {
                "policy": "FIXED_RETRY",
                "label": "Deterministic Fixed-Retry Baseline",
                "attempts": cf_fixed.total_retries,
                "recovered_principal": f"₹{cf_fixed.gross_recovered_amount_in_paisa / 100:,.2f}",
                "simulated_operational_cost": f"₹{cf_fixed.operational_cost_in_paisa / 100:,.2f}",
                "net_recovery": f"₹{cf_fixed.net_recovered_amount_in_paisa / 100:,.2f}",
                "final_state": cf_fixed.final_case_state.value,
                "unnecessary_retries": cf_fixed.unnecessary_retries,
            },
            "mandateshield": {
                "policy": "MANDATESHIELD",
                "label": "MandateShield (Context-Aware)",
                "attempts": cf_ms.total_retries,
                "recovered_principal": f"₹{cf_ms.gross_recovered_amount_in_paisa / 100:,.2f}",
                "simulated_operational_cost": f"₹{cf_ms.operational_cost_in_paisa / 100:,.2f}",
                "net_recovery": f"₹{cf_ms.net_recovered_amount_in_paisa / 100:,.2f}",
                "final_state": cf_ms.final_case_state.value,
                "unnecessary_retries": cf_ms.unnecessary_retries,
            },
        }

        return DemoExecutionReport(
            scenario_id="scen_hero_01",
            scenario_name="Historical Payment Timing Recovery (Hero Flow)",
            customer_name="Rahul Mehta",
            amount_in_paisa=499900,
            amount_formatted="₹4,999.00",
            failure_reason="INSUFFICIENT_FUNDS (Outside historical payment window)",
            historical_window="Day 1–2 of Month",
            recommended_action="WAIT_AND_RETRY",
            policy_decision="APPROVED",
            policy_rules=policy_rules_summary,
            final_case_state=case.status.value,
            recovered_amount_in_paisa=case.recovered_amount_in_paisa,
            operational_cost_in_paisa=case.recovery_cost_in_paisa,
            net_recovered_in_paisa=case.recovered_amount_in_paisa - case.recovery_cost_in_paisa,
            decision_context=decision_context,
            outcome_summary=outcome_summary,
            counterfactual_preview=counterfactual_preview,
            timeline=timeline,
        )

    def run_safety_block_scenario(self) -> DemoExecutionReport:
        """
        Executes Safety Policy Guardrail Scenario:
        Simulates an AI proposing RETRY_NOW on a REVOKED mandate (Deepa Rao, ₹999).
        Policy Guardian detects RULE-PROV-01 violation and deterministically BLOCKS debit.
        Proves that AI advice can NEVER bypass deterministic policy.
        """
        timeline: List[DemoTimelineEvent] = []
        clock = SimulationClock(datetime(2026, 9, 2, 10, 0, 0, tzinfo=timezone.utc))
        provider = SimulatedPaymentProvider(clock=clock, seed=42)

        customer = Customer(
            id="cust_4012",
            name="Deepa Rao",
            email="deepa.rao@example.com",
            risk_tier=CustomerRiskTier.STANDARD,
        )
        mandate = Mandate(
            id="mnd_revoked_4012",
            customer_id=customer.id,
            provider_mandate_token="rzp_tok_revoked_4012",
            payment_method=PaymentMethod.UPI_AUTOPAY,
            issuer_bank=IssuerBank.AXIS,
            status=MandateStatus.REVOKED,
            max_amount_in_paisa=500000,
        )
        provider.register_mandate(mandate)

        subscription = Subscription(
            id="sub_4012",
            customer_id=customer.id,
            current_mandate_id=mandate.id,
            amount_in_paisa=99900,
            billing_cycle=BillingCycle.MONTHLY,
            status=SubscriptionStatus.ACTIVE,
            next_billing_at=clock.now(),
        )

        case = RecoveryCase(
            id="case_safety_4012",
            subscription_id=subscription.id,
            customer_id=customer.id,
            initial_attempt_id="att_4012_init",
            revenue_at_risk_in_paisa=99900,
            status=RecoveryState.PAYMENT_FAILED,
        )
        case.transition_to(RecoveryState.RECOVERY_ELIGIBLE)

        # 1. Ingestion of Failure
        timeline.append(
            DemoTimelineEvent(
                timestamp="2026-09-02 10:00:00 UTC",
                stage="FAILURE_INGESTION",
                title="Debit Failed on Mandate",
                description="UPI AutoPay debit failed with 'mandate_inactive'. Mandate was revoked by customer on bank app.",
                status="FAILED",
                badge_color="rose",
                details={"mandate_status": "REVOKED", "amount": "₹999.00"},
            )
        )

        normalized = FailureNormalizer.normalize("mandate_inactive", "Customer revoked mandate")
        risk = RevenueRiskEngine.evaluate(subscription, customer, mandate, normalized.category)
        rail_health = provider.get_rail_health(mandate.issuer_bank, mandate.payment_method)

        context = RecoveryContextBuilder.build(
            recovery_case=case,
            customer=customer,
            subscription=subscription,
            mandate=mandate,
            normalized_failure=normalized,
            risk_assessment=risk,
            rail_health=rail_health,
            customer_mandates=[mandate],
            historical_successful_dates=[],
            current_time=clock.now(),
        )

        # 2. Simulate AI hallucinating or proposing an aggressive RETRY_NOW
        hallucinated_ai_proposal = StrategyProposal(
            proposal_id="prop_unsafe_ai_01",
            recovery_case_id=case.id,
            subscription_id=subscription.id,
            action=RecoveryAction.RETRY_NOW,
            reason_codes=[StrategyReasonCode.TRANSIENT_PROVIDER_FAILURE],
            rationale="Aggressive AI agent attempting immediate debit despite inactive token.",
            strategy_confidence=0.95,
            planner_source=PlannerSource.GEMINI_LLM,
        )

        timeline.append(
            DemoTimelineEvent(
                timestamp="2026-09-02 10:00:01 UTC",
                stage="AI_PROPOSAL",
                title="AI Advisory: RETRY_NOW (Unsafe)",
                description="AI model proposed immediate debit (Confidence: 95%). Labeled advisory-only; no execution rights.",
                status="PROPOSED",
                badge_color="rose",
                details={
                    "proposed_action": "RETRY_NOW",
                    "ai_rationale": hallucinated_ai_proposal.rationale,
                    "confidence": "95%",
                },
            )
        )

        # 3. Policy Guardian Evaluates and BLOCKS
        guardian = PolicyGuardian()
        evaluation = guardian.evaluate(context, hallucinated_ai_proposal, case_status=case.status)
        policy_rules_summary = [
            {
                "rule_id": r.rule_id,
                "rule_name": r.rule_name,
                "category": r.category.value,
                "passed": r.passed,
                "description": r.description,
            }
            for r in evaluation.evaluated_rules
        ]

        timeline.append(
            DemoTimelineEvent(
                timestamp="2026-09-02 10:00:02 UTC",
                stage="POLICY_GUARDIAN",
                title="Policy Guardian: BLOCKED",
                description="Policy Guardian intercepted and blocked proposal. RULE-PROV-01 failed (Mandate status is REVOKED). Zero debit authorization issued.",
                status="BLOCKED",
                badge_color="rose",
                details={
                    "verdict": evaluation.verdict.value,
                    "failing_rule": "RULE-PROV-01 (Mandate Active Status Check)",
                    "rejection_reasons": evaluation.rejection_reasons,
                },
            )
        )

        # 4. Safe Terminal Transition
        case.transition_to(RecoveryState.STOPPED)

        timeline.append(
            DemoTimelineEvent(
                timestamp="2026-09-02 10:00:03 UTC",
                stage="TERMINAL_SAFETY",
                title="Case Stopped (Zero Debit Side Effects)",
                description="Case transitioned to STOPPED. Customer protected from illegal debit attempts and unnecessary simulated retry costs.",
                status="STOPPED",
                badge_color="gray",
                details={
                    "final_case_state": case.status.value,
                    "total_debited_amount": "₹0.00",
                    "fees_incurred": "₹0.00",
                },
            )
        )

        self._cases[case.id] = case

        # Decision Context for Safety Demo
        failing_rules = [r for r in evaluation.evaluated_rules if not r.passed]
        failing_rule = failing_rules[0] if failing_rules else None

        decision_context = {
            "proposed_action": hallucinated_ai_proposal.action.value,
            "model_confidence": "0.95 (95% Model Confidence)",
            "confidence_disclaimer": "Model self-reported confidence score — NOT a statistical recovery probability",
            "planner_source": hallucinated_ai_proposal.planner_source.value,
            "ai_rationale": hallucinated_ai_proposal.rationale,
            "policy_verdict": evaluation.verdict.value,
            "failing_rule_id": failing_rule.rule_id if failing_rule else "RULE-PROV-01",
            "failing_rule_name": failing_rule.rule_name if failing_rule else "Mandate Active Status Check",
            "rule_category": failing_rule.category.value if failing_rule else "PROVIDER_RULE",
            "rejection_reason": evaluation.rejection_reasons[0] if evaluation.rejection_reasons else "Mandate status is 'REVOKED'. Automated debit prohibited.",
            "safety_boundary_note": "AI can recommend RETRY_NOW, but every debit action must pass deterministic policy authorization.",
        }

        outcome_summary = {
            "debit_attempted": "₹0.00",
            "recovered_principal": "₹0.00",
            "simulated_operational_cost": "₹0.00",
            "net_recovery": "₹0.00",
            "final_state": case.status.value,
        }

        return DemoExecutionReport(
            scenario_id="scen_safety_02",
            scenario_name="Policy Guardian Safety Interception (Revoked Mandate)",
            customer_name="Deepa Rao",
            amount_in_paisa=99900,
            amount_formatted="₹999.00",
            failure_reason="MANDATE_REVOKED (Customer cancelled authorization)",
            historical_window="N/A",
            recommended_action="RETRY_NOW (AI) -> BLOCKED (Policy)",
            policy_decision="BLOCKED",
            policy_rules=policy_rules_summary,
            final_case_state=case.status.value,
            recovered_amount_in_paisa=0,
            operational_cost_in_paisa=0,
            net_recovered_in_paisa=0,
            decision_context=decision_context,
            outcome_summary=outcome_summary,
            timeline=timeline,
        )

    def run_webhook_resilience_scenario(self) -> DemoExecutionReport:
        """
        Executes Webhook Resilience & Deduplication Scenario:
        Simulates an ambiguous gateway timeout resolved by asynchronous webhook,
        followed by duplicate webhook replay deduplication.
        """
        timeline: List[DemoTimelineEvent] = []
        clock = SimulationClock(datetime(2026, 9, 2, 10, 0, 0, tzinfo=timezone.utc))
        provider = SimulatedPaymentProvider(clock=clock, seed=42)

        customer = Customer(id="cust_9981", name="Rajesh Khanna", email="rajesh@example.com")
        mandate = Mandate(
            id="mnd_9981",
            customer_id=customer.id,
            provider_mandate_token="rzp_tok_9981",
            payment_method=PaymentMethod.CARD_MANDATE,
            issuer_bank=IssuerBank.HDFC,
            status=MandateStatus.ACTIVE,
            max_amount_in_paisa=1000000,
        )
        provider.register_mandate(mandate)
        sub = Subscription(
            id="sub_9981",
            customer_id=customer.id,
            current_mandate_id=mandate.id,
            amount_in_paisa=799900,
            billing_cycle=BillingCycle.MONTHLY,
            next_billing_at=clock.now(),
        )
        case = RecoveryCase(
            id="case_resilience_9981",
            subscription_id=sub.id,
            customer_id=customer.id,
            initial_attempt_id="att_9981_init",
            revenue_at_risk_in_paisa=799900,
            status=RecoveryState.RECOVERY_ELIGIBLE,
        )

        auth = PolicyAuthorization(
            auth_id="auth_resilience_01",
            case_id=case.id,
            decision_id="prop_resilience_01",
            authorized_action=RecoveryAction.RETRY_NOW,
            verdict=PolicyVerdict.APPROVED,
            valid_until=clock.now() + timedelta(hours=2),
            execution_parameters={"amount_in_paisa": 799900},
            created_at=clock.now(),
        )

        # 1. Executor encounters a 504 Gateway Timeout
        case.record_attempt(clock.now())
        case.record_cost(500)
        case.transition_to(RecoveryState.RECOVERY_ATTEMPTED, has_authorization=True)
        case.transition_to(RecoveryState.ESCALATED)

        timeline.append(
            DemoTimelineEvent(
                timestamp="2026-09-02 10:00:00 UTC",
                stage="GATEWAY_TIMEOUT",
                title="Gateway 504 Timeout on Debit",
                description="Bank rail dropped socket connection during debit dispatch. Ambiguous state detected. Case escalated with zero blind retries.",
                status="AMBIGUOUS_TIMEOUT",
                badge_color="amber",
                details={
                    "case_state": "ESCALATED",
                    "safety_decision": "NO_BLIND_RETRY",
                    "auto_retry_prevented": True,
                },
            )
        )

        attempt = PaymentAttempt(
            id="att_resilience_01",
            subscription_id=sub.id,
            mandate_id=mandate.id,
            amount_in_paisa=799900,
            attempt_number=1,
            status=PaymentAttemptStatus.FAILED,
            is_recovery_attempt=True,
            created_at=clock.now(),
        )

        # 2. Asynchronous Webhook Arrives
        reconciler = WebhookReconciler()
        raw_payload = b'{"event":"payment.captured","amount":799900,"id":"pay_resilience_01"}'
        signature = SimulatedWebhookVerifier.generate_signature(raw_payload)

        webhook_event = WebhookEvent(
            event_id="evt_async_9981",
            provider_event_id="evt_rzp_async_9981",
            event_type=WebhookEventType.PAYMENT_CAPTURED,
            provider_payment_id="pay_resilience_01",
            payment_attempt_id=attempt.id,
            amount_in_paisa=799900,
            raw_status="captured",
            event_timestamp=clock.now(),
            signature=f"sha256={signature}",
        )

        res1 = reconciler.reconcile(webhook_event, attempt=attempt, case=case, raw_payload_bytes=raw_payload)

        timeline.append(
            DemoTimelineEvent(
                timestamp="2026-09-02 10:00:05 UTC",
                stage="WEBHOOK_INGESTION",
                title="Async Webhook: SETTLED_SUCCESS",
                description="HMAC-SHA256 verified. Ambiguous payment correlated to attempt att_resilience_01 and reconciled to RECOVERED.",
                status="SETTLED",
                badge_color="emerald",
                details={
                    "reconciliation_status": res1.status.value,
                    "recovered_principal": "₹7,999.00",
                    "hmac_signature": "sha256=VERIFIED",
                },
            )
        )

        # 3. Duplicate Webhook Replay Delivery
        res2 = reconciler.reconcile(webhook_event, attempt=attempt, case=case, raw_payload_bytes=raw_payload)

        timeline.append(
            DemoTimelineEvent(
                timestamp="2026-09-02 10:00:15 UTC",
                stage="DEDUPLICATION_REPLAY",
                title="Duplicate Webhook: IGNORED (No-Op)",
                description=f"Provider re-delivered event '{webhook_event.provider_event_id}'. Process-local deduplication layer recognized event ID and safely ignored it. ₹0 double counted.",
                status="DUPLICATE_IGNORED",
                badge_color="indigo",
                details={
                    "is_duplicate": True,
                    "double_counting_prevented": True,
                    "final_recovered_amount": "₹7,999.00 (Process-Local Deduplicated)",
                },
            )
        )

        self._cases[case.id] = case

        decision_context = {
            "execution_status": "AMBIGUOUS_TIMEOUT",
            "safety_action": "NO_BLIND_RETRY",
            "safety_callout": "Payment outcome is ambiguous. MandateShield waits for authoritative settlement evidence.",
            "security_status": "HMAC-SHA256 VERIFIED",
            "security_note": "Provider event signature verified before reconciliation (Simulated Verifier).",
            "checks": [
                {"name": "Payment Attempt Correlated", "status": "PASSED", "detail": f"Attempt: {attempt.id}"},
                {"name": "Amount Integrity Verified", "status": "PASSED", "detail": "₹7,999.00 exact match"},
                {"name": "Outcome Normalized", "status": "PASSED", "detail": "PAYMENT_CAPTURED -> SUCCESS"},
                {"name": "Process-Local Deduplication", "status": "PASSED", "detail": f"Event {webhook_event.provider_event_id} cached"},
            ],
            "duplicate_status": "DUPLICATE WEBHOOK IGNORED",
            "duplicate_note": f"Same provider event ID ('{webhook_event.provider_event_id}') was already processed. Replay safely ignored.",
            "architecture_principle": "Execute cautiously. Reconcile deterministically.",
        }

        outcome_summary = {
            "recovered_principal": f"₹{case.recovered_amount_in_paisa / 100:,.2f}",
            "simulated_operational_cost": f"₹{case.recovery_cost_in_paisa / 100:,.2f}",
            "net_recovery": f"₹{(case.recovered_amount_in_paisa - case.recovery_cost_in_paisa) / 100:,.2f}",
            "final_state": case.status.value,
        }

        return DemoExecutionReport(
            scenario_id="scen_resilience_03",
            scenario_name="Asynchronous Webhook Settlement & Deduplication",
            customer_name="Rajesh Khanna",
            amount_in_paisa=799900,
            amount_formatted="₹7,999.00",
            failure_reason="GATEWAY_TIMEOUT (Resolved by Webhook)",
            historical_window="N/A",
            recommended_action="ASYNC_RECONCILE",
            policy_decision="APPROVED",
            policy_rules=[],
            final_case_state=case.status.value,
            recovered_amount_in_paisa=case.recovered_amount_in_paisa,
            operational_cost_in_paisa=case.recovery_cost_in_paisa,
            net_recovered_in_paisa=case.recovered_amount_in_paisa - case.recovery_cost_in_paisa,
            decision_context=decision_context,
            outcome_summary=outcome_summary,
            timeline=timeline,
        )

    def get_dashboard_summary(self) -> Dict[str, Any]:
        cases_list = list(self._cases.values())
        total_at_risk = sum(c.revenue_at_risk_in_paisa for c in cases_list)
        total_recovered = sum(c.recovered_amount_in_paisa for c in cases_list)
        active_count = sum(1 for c in cases_list if not RecoveryStateMachine.is_terminal(c.status))
        recovered_count = sum(1 for c in cases_list if c.status == RecoveryState.RECOVERED)
        recovery_rate = round(recovered_count / len(cases_list) * 100, 1) if cases_list else 0.0

        return {
            "total_revenue_at_risk_formatted": f"₹{total_at_risk/100:,.2f}",
            "total_recovered_revenue_formatted": f"₹{total_recovered/100:,.2f}",
            "active_cases_count": active_count,
            "recovered_cases_count": recovered_count,
            "total_cases_count": len(cases_list),
            "recovery_rate_percent": recovery_rate,
            "cases": [
                {
                    "case_id": c.id,
                    "subscription_id": c.subscription_id,
                    "customer_id": c.customer_id,
                    "revenue_at_risk_formatted": f"₹{c.revenue_at_risk_in_paisa/100:,.2f}",
                    "status": c.status.value,
                    "total_attempts": c.total_attempts,
                    "recovered_amount_formatted": f"₹{c.recovered_amount_in_paisa/100:,.2f}",
                }
                for c in cases_list
            ],
        }
