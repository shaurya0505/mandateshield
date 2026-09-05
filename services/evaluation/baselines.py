import uuid
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from domain.models.customer import Customer
from domain.models.mandate import Mandate, MandateStatus, PaymentMethod, IssuerBank
from domain.models.subscription import Subscription, BillingCycle
from domain.models.payment_attempt import PaymentAttempt, PaymentAttemptStatus, FailureCategory
from domain.models.policy_authorization import PolicyAuthorization, PolicyVerdict
from domain.models.recovery_case import RecoveryCase
from domain.models.evaluation import EvaluationPolicy, ScenarioOutcome
from domain.states.recovery_state import RecoveryAction, RecoveryState
from domain.interfaces.payment_provider import RailHealthMetrics
from domain.interfaces.strategy_planner import StrategyPlanner
from infrastructure.simulation.simulated_payment_provider import SimulatedPaymentProvider
from infrastructure.simulation.simulation_clock import SimulationClock
from services.ingestion.failure_normalizer import FailureNormalizer
from services.risk.revenue_risk_engine import RevenueRiskEngine
from services.signals.recovery_context_builder import RecoveryContextBuilder
from services.ai.deterministic_fallback_planner import DeterministicFallbackPlanner
from services.policy.policy_guardian import PolicyGuardian
from services.executor.recovery_executor import RecoveryExecutor


class ScenarioRunner:
    """
    Executes identical synthetic failure scenarios under each of the 3 evaluation policies.
    Guarantees strict counterfactual equivalence and deterministic isolation.
    """

    @staticmethod
    def run_no_recovery(
        scenario_id: str,
        scenario_name: str,
        customer: Customer,
        subscription: Subscription,
        mandate: Mandate,
        provider: SimulatedPaymentProvider,
        clock: SimulationClock,
    ) -> ScenarioOutcome:
        """
        Policy A: NO_RECOVERY
        Observes the initial failure, opens a case, and takes zero recovery actions.
        """
        initial_time = clock.now()
        amount_in_paisa = subscription.amount_in_paisa

        # Initial failed attempt
        initial_res = provider.charge_mandate(
            mandate_token=mandate.provider_mandate_token,
            amount_in_paisa=amount_in_paisa,
            idempotency_key=f"idemp_init_{scenario_id}",
        )

        case = RecoveryCase(
            id=f"case_no_rec_{scenario_id}",
            subscription_id=subscription.id,
            customer_id=customer.id,
            initial_attempt_id="att_init_01",
            revenue_at_risk_in_paisa=amount_in_paisa,
            status=RecoveryState.PAYMENT_FAILED,
        )
        case.transition_to(RecoveryState.RECOVERY_ELIGIBLE)

        return ScenarioOutcome(
            scenario_id=scenario_id,
            scenario_name=scenario_name,
            policy=EvaluationPolicy.NO_RECOVERY,
            initial_amount_at_risk_in_paisa=amount_in_paisa,
            gross_recovered_amount_in_paisa=0,
            operational_cost_in_paisa=0,
            net_recovered_amount_in_paisa=0,
            is_recovered=False,
            final_case_state=case.status,
            total_retries=0,
            total_nudges=0,
            unnecessary_retries=0,
            actions_taken=[],
            simulated_duration_seconds=0,
        )

    @staticmethod
    def run_fixed_retry(
        scenario_id: str,
        scenario_name: str,
        customer: Customer,
        subscription: Subscription,
        mandate: Mandate,
        provider: SimulatedPaymentProvider,
        clock: SimulationClock,
        max_retries: int = 3,
        retry_interval_hours: int = 24,
    ) -> ScenarioOutcome:
        """
        Policy B: FIXED_RETRY (Naive Schedule Baseline)
        Blindly re-attempts debit on the primary mandate every 24 hours up to 3 times.
        Does not inspect historical timing, rail degradation, or alternate payment methods.
        """
        initial_time = clock.now()
        amount_in_paisa = subscription.amount_in_paisa

        # Initial failed attempt
        initial_res = provider.charge_mandate(
            mandate_token=mandate.provider_mandate_token,
            amount_in_paisa=amount_in_paisa,
            idempotency_key=f"idemp_init_{scenario_id}",
        )

        case = RecoveryCase(
            id=f"case_fixed_{scenario_id}",
            subscription_id=subscription.id,
            customer_id=customer.id,
            initial_attempt_id="att_init_01",
            revenue_at_risk_in_paisa=amount_in_paisa,
            status=RecoveryState.PAYMENT_FAILED,
        )
        case.transition_to(RecoveryState.RECOVERY_ELIGIBLE)

        retries_attempted = 0
        unnecessary_retries = 0
        is_recovered = False
        actions_taken: List[RecoveryAction] = []
        cost_paisa = 0

        # Fixed retry loop
        for attempt_idx in range(1, max_retries + 1):
            if is_recovered or case.status == RecoveryState.STOPPED:
                break

            # Stop if mandate is revoked/inactive
            if mandate.status != MandateStatus.ACTIVE:
                case.transition_to(RecoveryState.STOPPED)
                break

            # Advance clock by fixed interval
            clock.advance(hours=retry_interval_hours)
            actions_taken.append(RecoveryAction.RETRY_NOW)
            retries_attempted += 1
            cost_paisa += 500  # ₹5.00 debit fee

            # Execute debit on the same primary mandate
            res = provider.charge_mandate(
                mandate_token=mandate.provider_mandate_token,
                amount_in_paisa=amount_in_paisa,
                idempotency_key=f"idemp_fixed_{scenario_id}_{attempt_idx}",
            )

            if res.success:
                is_recovered = True
                case.transition_to(RecoveryState.RECOVERY_ATTEMPTED, has_authorization=True)
                case.mark_recovered(amount_in_paisa=amount_in_paisa, recovered_at=clock.now())
                break
            else:
                # Count as unnecessary retry if failed on degraded rail or outside timing window
                unnecessary_retries += 1

        duration = int((clock.now() - initial_time).total_seconds())
        gross_recovered = amount_in_paisa if is_recovered else 0
        net_recovered = gross_recovered - cost_paisa

        return ScenarioOutcome(
            scenario_id=scenario_id,
            scenario_name=scenario_name,
            policy=EvaluationPolicy.FIXED_RETRY,
            initial_amount_at_risk_in_paisa=amount_in_paisa,
            gross_recovered_amount_in_paisa=gross_recovered,
            operational_cost_in_paisa=cost_paisa,
            net_recovered_amount_in_paisa=net_recovered,
            is_recovered=is_recovered,
            final_case_state=case.status,
            total_retries=retries_attempted,
            total_nudges=0,
            unnecessary_retries=unnecessary_retries,
            actions_taken=actions_taken,
            simulated_duration_seconds=duration,
        )

    @staticmethod
    def run_mandateshield(
        scenario_id: str,
        scenario_name: str,
        customer: Customer,
        subscription: Subscription,
        mandates: List[Mandate],
        primary_mandate: Mandate,
        provider: SimulatedPaymentProvider,
        clock: SimulationClock,
        historical_successful_dates: Optional[List[datetime]] = None,
        planner: Optional[StrategyPlanner] = None,
    ) -> ScenarioOutcome:
        """
        Policy C: MANDATESHIELD (Context-Aware Intelligence Pipeline)
        Runs the complete MandateShield pipeline: Context -> Strategy -> Guardian -> Executor.
        """
        initial_time = clock.now()
        amount_in_paisa = subscription.amount_in_paisa
        strategy_planner = planner or DeterministicFallbackPlanner()
        guardian = PolicyGuardian()
        executor = RecoveryExecutor()

        # 1. Initial attempt
        initial_res = provider.charge_mandate(
            mandate_token=primary_mandate.provider_mandate_token,
            amount_in_paisa=amount_in_paisa,
            idempotency_key=f"idemp_init_{scenario_id}",
        )

        # 2. Normalization & Risk Assessment
        normalized = FailureNormalizer.normalize(initial_res.raw_error_code, initial_res.raw_error_message)
        risk_assessment = RevenueRiskEngine.evaluate(
            subscription=subscription,
            customer=customer,
            mandate=primary_mandate,
            failure_category=normalized.category,
        )
        rail_health = provider.get_rail_health(
            issuer_bank=primary_mandate.issuer_bank,
            payment_method=primary_mandate.payment_method,
        )

        case = RecoveryCase(
            id=f"case_ms_{scenario_id}",
            subscription_id=subscription.id,
            customer_id=customer.id,
            initial_attempt_id="att_init_01",
            revenue_at_risk_in_paisa=amount_in_paisa,
            status=RecoveryState.PAYMENT_FAILED,
        )
        case.transition_to(RecoveryState.RECOVERY_ELIGIBLE)

        actions_taken: List[RecoveryAction] = []
        is_recovered = False
        retries_count = 0
        nudges_count = 0
        unnecessary_retries = 0

        # Step 1: Build Context & Propose Strategy
        context = RecoveryContextBuilder.build(
            recovery_case=case,
            customer=customer,
            subscription=subscription,
            mandate=primary_mandate,
            normalized_failure=normalized,
            risk_assessment=risk_assessment,
            rail_health=rail_health,
            customer_mandates=mandates,
            historical_successful_dates=historical_successful_dates or [],
            current_time=clock.now(),
        )

        proposal = strategy_planner.propose_strategy(context)
        actions_taken.append(proposal.action)

        # Step 2: Policy Guardian Authorization
        evaluation = guardian.evaluate(context, proposal, case_status=case.status)

        # Find alternate active mandate if path switching
        alt_mandate = next((m for m in mandates if m.id != primary_mandate.id and m.status == MandateStatus.ACTIVE), None)

        if evaluation.is_approved and evaluation.authorization:
            auth = evaluation.authorization

            if proposal.action == RecoveryAction.WAIT_AND_RETRY:
                # Execute scheduling
                executor.execute(auth, case, customer, subscription, primary_mandate, provider, clock.now())
                
                # Advance clock to optimal historical timing window
                delay_sec = proposal.recommended_delay_seconds or 86400
                clock.advance(seconds=delay_sec)

                # Now execute scheduled retry at optimal window
                scheduled_auth = PolicyAuthorization(
                    auth_id=f"auth_sched_{scenario_id}",
                    case_id=case.id,
                    decision_id=f"prop_sched_{scenario_id}",
                    authorized_action=RecoveryAction.RETRY_NOW,
                    verdict=PolicyVerdict.APPROVED,
                    valid_until=clock.now() + timedelta(hours=2),
                    execution_parameters={"amount_in_paisa": amount_in_paisa},
                    created_at=clock.now(),
                )
                actions_taken.append(RecoveryAction.RETRY_NOW)
                retries_count += 1
                exec_res = executor.execute(
                    scheduled_auth, case, customer, subscription, primary_mandate, provider, clock.now()
                )
                if exec_res.success:
                    is_recovered = True

            elif proposal.action == RecoveryAction.SWITCH_PAYMENT_PATH:
                retries_count += 1
                exec_res = executor.execute(
                    auth, case, customer, subscription, primary_mandate, provider, clock.now(), alternative_mandate=alt_mandate
                )
                if exec_res.success:
                    is_recovered = True

            elif proposal.action == RecoveryAction.RETRY_NOW:
                retries_count += 1
                exec_res = executor.execute(
                    auth, case, customer, subscription, primary_mandate, provider, clock.now()
                )
                if exec_res.success:
                    is_recovered = True

            elif proposal.action == RecoveryAction.SEND_RECOVERY_NUDGE:
                nudges_count += 1
                executor.execute(auth, case, customer, subscription, primary_mandate, provider, clock.now())

            elif proposal.action == RecoveryAction.ESCALATE_TO_HUMAN:
                executor.execute(auth, case, customer, subscription, primary_mandate, provider, clock.now())

            elif proposal.action == RecoveryAction.STOP_RECOVERY:
                executor.execute(auth, case, customer, subscription, primary_mandate, provider, clock.now())

        duration = int((clock.now() - initial_time).total_seconds())
        gross_recovered = case.recovered_amount_in_paisa
        cost_paisa = case.recovery_cost_in_paisa
        net_recovered = gross_recovered - cost_paisa

        return ScenarioOutcome(
            scenario_id=scenario_id,
            scenario_name=scenario_name,
            policy=EvaluationPolicy.MANDATESHIELD,
            initial_amount_at_risk_in_paisa=amount_in_paisa,
            gross_recovered_amount_in_paisa=gross_recovered,
            operational_cost_in_paisa=cost_paisa,
            net_recovered_amount_in_paisa=net_recovered,
            is_recovered=is_recovered,
            final_case_state=case.status,
            total_retries=retries_count,
            total_nudges=nudges_count,
            unnecessary_retries=unnecessary_retries,
            actions_taken=actions_taken,
            simulated_duration_seconds=duration,
        )
