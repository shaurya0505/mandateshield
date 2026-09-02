from datetime import datetime, timezone
from typing import NamedTuple, List
from domain.models.customer import Customer, CustomerRiskTier
from domain.models.mandate import Mandate, MandateStatus, PaymentMethod, IssuerBank
from domain.models.subscription import Subscription, SubscriptionStatus, BillingCycle
from infrastructure.simulation.simulation_clock import SimulationClock
from infrastructure.simulation.simulated_payment_provider import SimulatedPaymentProvider


class SyntheticScenarioSetup(NamedTuple):
    customer: Customer
    mandates: List[Mandate]
    primary_mandate: Mandate
    subscription: Subscription
    clock: SimulationClock
    provider: SimulatedPaymentProvider


class SyntheticScenarioGenerator:
    """
    Factory for generating deterministic, reproducible test scenarios.
    Used for unit testing, integration tests, and batch benchmark evaluation.
    """

    @staticmethod
    def create_insufficient_funds_scenario(seed: int = 42) -> SyntheticScenarioSetup:
        """
        Scenario: Customer C1029 with monthly ₹4,999 subscription.
        Clock set to August 28th (outside Day 1-4 liquidity window).
        First attempt fails with insufficient funds; succeeds after advancing to Sept 2nd.
        """
        clock = SimulationClock(datetime(2026, 8, 28, 10, 0, 0, tzinfo=timezone.utc))
        provider = SimulatedPaymentProvider(clock=clock, seed=seed)

        customer = Customer(
            id="cust_1029",
            name="Rahul Mehta",
            email="rahul.mehta@example.com",
            risk_tier=CustomerRiskTier.STANDARD,
        )

        mandate = Mandate(
            id="mnd_hdfc_1029",
            customer_id="cust_1029",
            provider_mandate_token="rzp_tok_hdfc_1029",
            payment_method=PaymentMethod.CARD_MANDATE,
            issuer_bank=IssuerBank.HDFC,
            status=MandateStatus.ACTIVE,
            max_amount_in_paisa=1500000,  # ₹15,000 limit
        )

        provider.register_mandate(mandate, liquidity_window_days=(1, 4))

        subscription = Subscription(
            id="sub_1029",
            customer_id="cust_1029",
            current_mandate_id=mandate.id,
            amount_in_paisa=499900,  # ₹4,999.00
            billing_cycle=BillingCycle.MONTHLY,
            status=SubscriptionStatus.ACTIVE,
            next_billing_at=datetime(2026, 8, 28, 10, 0, 0, tzinfo=timezone.utc),
        )

        return SyntheticScenarioSetup(
            customer=customer,
            mandates=[mandate],
            primary_mandate=mandate,
            subscription=subscription,
            clock=clock,
            provider=provider,
        )

    @staticmethod
    def create_transient_issuer_glitch_scenario(seed: int = 42) -> SyntheticScenarioSetup:
        """
        Scenario: Transient 503 bank error on HDFC card that succeeds on immediate retry.
        """
        clock = SimulationClock(datetime(2026, 9, 2, 10, 0, 0, tzinfo=timezone.utc))
        provider = SimulatedPaymentProvider(clock=clock, seed=seed)

        customer = Customer(
            id="cust_2041",
            name="Ananya Roy",
            email="ananya.roy@example.com",
            risk_tier=CustomerRiskTier.STANDARD,
        )

        mandate = Mandate(
            id="mnd_hdfc_2041",
            customer_id="cust_2041",
            provider_mandate_token="rzp_tok_hdfc_2041",
            payment_method=PaymentMethod.CARD_MANDATE,
            issuer_bank=IssuerBank.HDFC,
            status=MandateStatus.ACTIVE,
            max_amount_in_paisa=1000000,
        )

        provider.register_mandate(mandate, liquidity_window_days=(1, 4))
        provider.inject_transient_glitch(mandate.provider_mandate_token, fail_count=1)

        subscription = Subscription(
            id="sub_2041",
            customer_id="cust_2041",
            current_mandate_id=mandate.id,
            amount_in_paisa=199900,  # ₹1,999.00
            billing_cycle=BillingCycle.MONTHLY,
            status=SubscriptionStatus.ACTIVE,
            next_billing_at=clock.now(),
        )

        return SyntheticScenarioSetup(
            customer=customer,
            mandates=[mandate],
            primary_mandate=mandate,
            subscription=subscription,
            clock=clock,
            provider=provider,
        )

    @staticmethod
    def create_rail_degradation_scenario(seed: int = 42) -> SyntheticScenarioSetup:
        """
        Scenario: SBI UPI AutoPay degradation outage active for 4 hours.
        Primary SBI mandate fails; alternate ICICI card mandate is available.
        """
        clock = SimulationClock(datetime(2026, 9, 2, 14, 0, 0, tzinfo=timezone.utc))
        provider = SimulatedPaymentProvider(clock=clock, seed=seed)

        # Inject 4-hour SBI outage starting at 13:00 UTC
        provider.inject_rail_degradation(
            issuer_bank=IssuerBank.SBI,
            payment_method=PaymentMethod.UPI_AUTOPAY,
            start_time=datetime(2026, 9, 2, 13, 0, 0, tzinfo=timezone.utc),
            duration_hours=4,
            degraded_success_rate=0.05,  # 95% failure rate during outage
        )

        customer = Customer(
            id="cust_3088",
            name="Vikram Seth",
            email="vikram.seth@example.com",
            risk_tier=CustomerRiskTier.STANDARD,
        )

        mandate_sbi = Mandate(
            id="mnd_sbi_3088",
            customer_id="cust_3088",
            provider_mandate_token="rzp_tok_sbi_3088",
            payment_method=PaymentMethod.UPI_AUTOPAY,
            issuer_bank=IssuerBank.SBI,
            status=MandateStatus.ACTIVE,
            max_amount_in_paisa=1000000,
        )

        mandate_icici = Mandate(
            id="mnd_icici_3088",
            customer_id="cust_3088",
            provider_mandate_token="rzp_tok_icici_3088",
            payment_method=PaymentMethod.CARD_MANDATE,
            issuer_bank=IssuerBank.ICICI,
            status=MandateStatus.ACTIVE,
            max_amount_in_paisa=1000000,
        )

        provider.register_mandate(mandate_sbi, liquidity_window_days=(1, 4))
        provider.register_mandate(mandate_icici, liquidity_window_days=(1, 4))

        subscription = Subscription(
            id="sub_3088",
            customer_id="cust_3088",
            current_mandate_id=mandate_sbi.id,
            amount_in_paisa=249900,  # ₹2,499.00
            billing_cycle=BillingCycle.MONTHLY,
            status=SubscriptionStatus.ACTIVE,
            next_billing_at=clock.now(),
        )

        return SyntheticScenarioSetup(
            customer=customer,
            mandates=[mandate_sbi, mandate_icici],
            primary_mandate=mandate_sbi,
            subscription=subscription,
            clock=clock,
            provider=provider,
        )

    @staticmethod
    def create_revoked_mandate_scenario(seed: int = 42) -> SyntheticScenarioSetup:
        """
        Scenario: Customer revoked mandate on bank app.
        Attempts fail with mandate_inactive and must not be retried.
        """
        clock = SimulationClock(datetime(2026, 9, 2, 10, 0, 0, tzinfo=timezone.utc))
        provider = SimulatedPaymentProvider(clock=clock, seed=seed)

        customer = Customer(
            id="cust_4012",
            name="Deepa Rao",
            email="deepa.rao@example.com",
            risk_tier=CustomerRiskTier.STANDARD,
        )

        mandate = Mandate(
            id="mnd_revoked_4012",
            customer_id="cust_4012",
            provider_mandate_token="rzp_tok_revoked_4012",
            payment_method=PaymentMethod.UPI_AUTOPAY,
            issuer_bank=IssuerBank.AXIS,
            status=MandateStatus.REVOKED,
            max_amount_in_paisa=500000,
        )

        provider.register_mandate(mandate)

        subscription = Subscription(
            id="sub_4012",
            customer_id="cust_4012",
            current_mandate_id=mandate.id,
            amount_in_paisa=99900,  # ₹999.00
            billing_cycle=BillingCycle.MONTHLY,
            status=SubscriptionStatus.ACTIVE,
            next_billing_at=clock.now(),
        )

        return SyntheticScenarioSetup(
            customer=customer,
            mandates=[mandate],
            primary_mandate=mandate,
            subscription=subscription,
            clock=clock,
            provider=provider,
        )
