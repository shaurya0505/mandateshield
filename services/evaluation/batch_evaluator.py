import random
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from domain.models.customer import Customer, CustomerRiskTier
from domain.models.mandate import Mandate, MandateStatus, PaymentMethod, IssuerBank
from domain.models.subscription import Subscription, SubscriptionStatus, BillingCycle
from domain.models.evaluation import (
    EvaluationPolicy,
    PairedScenarioResult,
    BatchEvaluationResult,
)
from domain.interfaces.strategy_planner import StrategyPlanner
from infrastructure.simulation.simulation_clock import SimulationClock
from infrastructure.simulation.simulated_payment_provider import SimulatedPaymentProvider
from services.evaluation.baselines import ScenarioRunner
from services.evaluation.metrics_calculator import MetricsCalculator


class BatchEvaluator:
    """
    Deterministic Batch Counterfactual Evaluator.
    Generates representative synthetic payment failure scenarios and evaluates each under
    NO_RECOVERY, FIXED_RETRY, and MANDATESHIELD in strict paired counterfactual isolation.
    """

    def __init__(self, planner: Optional[StrategyPlanner] = None):
        self.planner = planner

    def evaluate(self, seed: int = 42, scenario_count: int = 20) -> BatchEvaluationResult:
        eval_id = f"eval_run_{uuid.uuid4().hex[:10]}"
        rng = random.Random(seed)
        paired_results: List[PairedScenarioResult] = []

        scenario_archetypes = [
            "LIQUIDITY_DEFICIT",
            "TRANSIENT_ISSUER_GLITCH",
            "RAIL_DEGRADATION_WITH_ALT",
            "RAIL_DEGRADATION_NO_ALT",
            "REVOKED_MANDATE",
            "HIGH_VALUE_REPEAT_FAILURE",
        ]

        for i in range(scenario_count):
            archetype = scenario_archetypes[i % len(scenario_archetypes)]
            scenario_seed = seed + i * 100
            scenario_id = f"scen_{i+1:03d}_{archetype.lower()}"

            # Run paired evaluation for this scenario archetype
            paired = self._run_paired_scenario(
                scenario_id=scenario_id,
                archetype=archetype,
                scenario_seed=scenario_seed,
                index=i,
            )
            paired_results.append(paired)

        # Aggregate metrics across the batch
        no_rec_outcomes = [p.no_recovery for p in paired_results]
        fixed_outcomes = [p.fixed_retry for p in paired_results]
        ms_outcomes = [p.mandateshield for p in paired_results]

        summary_no = MetricsCalculator.compute_policy_summary(EvaluationPolicy.NO_RECOVERY, no_rec_outcomes)
        summary_fixed = MetricsCalculator.compute_policy_summary(EvaluationPolicy.FIXED_RETRY, fixed_outcomes)
        summary_ms = MetricsCalculator.compute_policy_summary(EvaluationPolicy.MANDATESHIELD, ms_outcomes)

        lift = MetricsCalculator.compute_lift_metrics(
            mandateshield=summary_ms,
            no_recovery=summary_no,
            fixed_retry=summary_fixed,
        )

        return BatchEvaluationResult(
            evaluation_id=eval_id,
            seed=seed,
            scenario_count=scenario_count,
            policy_summaries={
                EvaluationPolicy.NO_RECOVERY: summary_no,
                EvaluationPolicy.FIXED_RETRY: summary_fixed,
                EvaluationPolicy.MANDATESHIELD: summary_ms,
            },
            lift_metrics=lift,
            paired_results=paired_results,
            evaluated_at=datetime.now(timezone.utc),
        )

    def _run_paired_scenario(
        self,
        scenario_id: str,
        archetype: str,
        scenario_seed: int,
        index: int,
    ) -> PairedScenarioResult:
        """
        Creates three identical scenario clones (one for each policy) and executes them.
        """
        # Parameters
        base_amounts = [99900, 199900, 299900, 499900, 799900, 1499900, 2999900]
        amount_in_paisa = base_amounts[index % len(base_amounts)]
        if archetype == "HIGH_VALUE_REPEAT_FAILURE":
            amount_in_paisa = 3000000  # ₹30,000.00

        # Build setups for each policy
        def _build_setup():
            if archetype == "LIQUIDITY_DEFICIT":
                clock = SimulationClock(datetime(2026, 8, 28, 10, 0, 0, tzinfo=timezone.utc))
                provider = SimulatedPaymentProvider(clock=clock, seed=scenario_seed)
                cust = Customer(id=f"cust_{index}", name=f"Customer {index}", email=f"c{index}@example.com")
                mnd = Mandate(
                    id=f"mnd_{index}_1",
                    customer_id=cust.id,
                    provider_mandate_token=f"rzp_tok_{index}_1",
                    payment_method=PaymentMethod.CARD_MANDATE,
                    issuer_bank=IssuerBank.HDFC,
                    status=MandateStatus.ACTIVE,
                    max_amount_in_paisa=5000000,
                )
                provider.register_mandate(mnd, liquidity_window_days=(1, 4))
                sub = Subscription(
                    id=f"sub_{index}",
                    customer_id=cust.id,
                    current_mandate_id=mnd.id,
                    amount_in_paisa=amount_in_paisa,
                    billing_cycle=BillingCycle.MONTHLY,
                    next_billing_at=clock.now(),
                )
                past_dates = [
                    datetime(2026, 6, 2, 10, 0, 0, tzinfo=timezone.utc),
                    datetime(2026, 7, 1, 10, 0, 0, tzinfo=timezone.utc),
                    datetime(2026, 8, 1, 10, 0, 0, tzinfo=timezone.utc),
                ]
                return cust, [mnd], mnd, sub, provider, clock, past_dates

            elif archetype == "TRANSIENT_ISSUER_GLITCH":
                clock = SimulationClock(datetime(2026, 9, 2, 10, 0, 0, tzinfo=timezone.utc))
                provider = SimulatedPaymentProvider(clock=clock, seed=scenario_seed)
                cust = Customer(id=f"cust_{index}", name=f"Customer {index}", email=f"c{index}@example.com")
                mnd = Mandate(
                    id=f"mnd_{index}_1",
                    customer_id=cust.id,
                    provider_mandate_token=f"rzp_tok_{index}_1",
                    payment_method=PaymentMethod.CARD_MANDATE,
                    issuer_bank=IssuerBank.HDFC,
                    status=MandateStatus.ACTIVE,
                    max_amount_in_paisa=5000000,
                )
                provider.register_mandate(mnd, liquidity_window_days=(1, 4))
                provider.inject_transient_glitch(mnd.provider_mandate_token, fail_count=1)
                sub = Subscription(
                    id=f"sub_{index}",
                    customer_id=cust.id,
                    current_mandate_id=mnd.id,
                    amount_in_paisa=amount_in_paisa,
                    billing_cycle=BillingCycle.MONTHLY,
                    next_billing_at=clock.now(),
                )
                return cust, [mnd], mnd, sub, provider, clock, []

            elif archetype == "RAIL_DEGRADATION_WITH_ALT":
                clock = SimulationClock(datetime(2026, 9, 2, 14, 0, 0, tzinfo=timezone.utc))
                provider = SimulatedPaymentProvider(clock=clock, seed=scenario_seed)
                provider.inject_rail_degradation(
                    issuer_bank=IssuerBank.SBI,
                    payment_method=PaymentMethod.UPI_AUTOPAY,
                    start_time=datetime(2026, 9, 2, 13, 0, 0, tzinfo=timezone.utc),
                    duration_hours=4,
                    degraded_success_rate=0.05,
                )
                cust = Customer(id=f"cust_{index}", name=f"Customer {index}", email=f"c{index}@example.com")
                mnd_sbi = Mandate(
                    id=f"mnd_sbi_{index}",
                    customer_id=cust.id,
                    provider_mandate_token=f"rzp_tok_sbi_{index}",
                    payment_method=PaymentMethod.UPI_AUTOPAY,
                    issuer_bank=IssuerBank.SBI,
                    status=MandateStatus.ACTIVE,
                    max_amount_in_paisa=5000000,
                )
                mnd_icici = Mandate(
                    id=f"mnd_icici_{index}",
                    customer_id=cust.id,
                    provider_mandate_token=f"rzp_tok_icici_{index}",
                    payment_method=PaymentMethod.CARD_MANDATE,
                    issuer_bank=IssuerBank.ICICI,
                    status=MandateStatus.ACTIVE,
                    max_amount_in_paisa=5000000,
                )
                provider.register_mandate(mnd_sbi, liquidity_window_days=(1, 4))
                provider.register_mandate(mnd_icici, liquidity_window_days=(1, 4))
                sub = Subscription(
                    id=f"sub_{index}",
                    customer_id=cust.id,
                    current_mandate_id=mnd_sbi.id,
                    amount_in_paisa=amount_in_paisa,
                    billing_cycle=BillingCycle.MONTHLY,
                    next_billing_at=clock.now(),
                )
                return cust, [mnd_sbi, mnd_icici], mnd_sbi, sub, provider, clock, []

            elif archetype == "RAIL_DEGRADATION_NO_ALT":
                clock = SimulationClock(datetime(2026, 9, 2, 14, 0, 0, tzinfo=timezone.utc))
                provider = SimulatedPaymentProvider(clock=clock, seed=scenario_seed)
                provider.inject_rail_degradation(
                    issuer_bank=IssuerBank.SBI,
                    payment_method=PaymentMethod.UPI_AUTOPAY,
                    start_time=datetime(2026, 9, 2, 13, 0, 0, tzinfo=timezone.utc),
                    duration_hours=4,
                    degraded_success_rate=0.05,
                )
                cust = Customer(id=f"cust_{index}", name=f"Customer {index}", email=f"c{index}@example.com")
                mnd_sbi = Mandate(
                    id=f"mnd_sbi_{index}",
                    customer_id=cust.id,
                    provider_mandate_token=f"rzp_tok_sbi_{index}",
                    payment_method=PaymentMethod.UPI_AUTOPAY,
                    issuer_bank=IssuerBank.SBI,
                    status=MandateStatus.ACTIVE,
                    max_amount_in_paisa=5000000,
                )
                provider.register_mandate(mnd_sbi, liquidity_window_days=(1, 4))
                sub = Subscription(
                    id=f"sub_{index}",
                    customer_id=cust.id,
                    current_mandate_id=mnd_sbi.id,
                    amount_in_paisa=amount_in_paisa,
                    billing_cycle=BillingCycle.MONTHLY,
                    next_billing_at=clock.now(),
                )
                return cust, [mnd_sbi], mnd_sbi, sub, provider, clock, []

            elif archetype == "REVOKED_MANDATE":
                clock = SimulationClock(datetime(2026, 9, 2, 10, 0, 0, tzinfo=timezone.utc))
                provider = SimulatedPaymentProvider(clock=clock, seed=scenario_seed)
                cust = Customer(id=f"cust_{index}", name=f"Customer {index}", email=f"c{index}@example.com")
                mnd = Mandate(
                    id=f"mnd_revoked_{index}",
                    customer_id=cust.id,
                    provider_mandate_token=f"rzp_tok_revoked_{index}",
                    payment_method=PaymentMethod.CARD_MANDATE,
                    issuer_bank=IssuerBank.HDFC,
                    status=MandateStatus.REVOKED,
                    max_amount_in_paisa=5000000,
                )
                provider.register_mandate(mnd)
                sub = Subscription(
                    id=f"sub_{index}",
                    customer_id=cust.id,
                    current_mandate_id=mnd.id,
                    amount_in_paisa=amount_in_paisa,
                    billing_cycle=BillingCycle.MONTHLY,
                    next_billing_at=clock.now(),
                )
                return cust, [mnd], mnd, sub, provider, clock, []

            else:  # HIGH_VALUE_REPEAT_FAILURE
                clock = SimulationClock(datetime(2026, 9, 2, 10, 0, 0, tzinfo=timezone.utc))
                provider = SimulatedPaymentProvider(clock=clock, seed=scenario_seed)
                cust = Customer(id=f"cust_{index}", name=f"Customer {index}", email=f"c{index}@example.com", risk_tier=CustomerRiskTier.HIGH)
                mnd = Mandate(
                    id=f"mnd_hv_{index}",
                    customer_id=cust.id,
                    provider_mandate_token=f"rzp_tok_hv_{index}",
                    payment_method=PaymentMethod.CARD_MANDATE,
                    issuer_bank=IssuerBank.HDFC,
                    status=MandateStatus.ACTIVE,
                    max_amount_in_paisa=10000000,
                )
                provider.register_mandate(mnd)
                sub = Subscription(
                    id=f"sub_hv_{index}",
                    customer_id=cust.id,
                    current_mandate_id=mnd.id,
                    amount_in_paisa=3000000,
                    billing_cycle=BillingCycle.MONTHLY,
                    next_billing_at=clock.now(),
                )
                return cust, [mnd], mnd, sub, provider, clock, []

        # 1. Run Policy A: NO_RECOVERY
        cust_a, _, mnd_a, sub_a, prov_a, clk_a, _ = _build_setup()
        outcome_no_rec = ScenarioRunner.run_no_recovery(
            scenario_id=scenario_id,
            scenario_name=f"{archetype} Scenario #{index+1}",
            customer=cust_a,
            subscription=sub_a,
            mandate=mnd_a,
            provider=prov_a,
            clock=clk_a,
        )

        # 2. Run Policy B: FIXED_RETRY
        cust_b, _, mnd_b, sub_b, prov_b, clk_b, _ = _build_setup()
        outcome_fixed = ScenarioRunner.run_fixed_retry(
            scenario_id=scenario_id,
            scenario_name=f"{archetype} Scenario #{index+1}",
            customer=cust_b,
            subscription=sub_b,
            mandate=mnd_b,
            provider=prov_b,
            clock=clk_b,
        )

        # 3. Run Policy C: MANDATESHIELD
        cust_c, mnds_c, mnd_c, sub_c, prov_c, clk_c, hist_c = _build_setup()
        outcome_ms = ScenarioRunner.run_mandateshield(
            scenario_id=scenario_id,
            scenario_name=f"{archetype} Scenario #{index+1}",
            customer=cust_c,
            subscription=sub_c,
            mandates=mnds_c,
            primary_mandate=mnd_c,
            provider=prov_c,
            clock=clk_c,
            historical_successful_dates=hist_c,
            planner=self.planner,
        )

        return PairedScenarioResult(
            scenario_id=scenario_id,
            scenario_name=f"{archetype} Scenario #{index+1}",
            failure_mode=archetype,
            no_recovery=outcome_no_rec,
            fixed_retry=outcome_fixed,
            mandateshield=outcome_ms,
        )
