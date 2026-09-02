import pytest
from datetime import datetime, timezone
from domain.interfaces.payment_provider import PaymentProvider
from domain.models.mandate import IssuerBank, PaymentMethod
from infrastructure.simulation.simulation_clock import SimulationClock
from infrastructure.simulation.simulated_payment_provider import SimulatedPaymentProvider
from infrastructure.simulation.synthetic_scenario_generator import SyntheticScenarioGenerator


def test_simulation_clock_behavior():
    """Verify deterministic virtual clock progression and constraints."""
    initial_dt = datetime(2026, 8, 28, 10, 0, 0, tzinfo=timezone.utc)
    clock = SimulationClock(initial_dt)
    assert clock.now() == initial_dt

    # Advance by 3 days and 4 hours
    clock.advance(days=3, hours=4)
    assert clock.now() == datetime(2026, 8, 31, 14, 0, 0, tzinfo=timezone.utc)

    # Disallow backwards movement
    with pytest.raises(ValueError):
        clock.advance(days=-1)


def test_deterministic_replay():
    """Verify exact seeded replay reproducibility across runs."""
    setup1 = SyntheticScenarioGenerator.create_insufficient_funds_scenario(seed=123)
    setup2 = SyntheticScenarioGenerator.create_insufficient_funds_scenario(seed=123)

    res1 = setup1.provider.charge_mandate(
        mandate_token=setup1.primary_mandate.provider_mandate_token,
        amount_in_paisa=setup1.subscription.amount_in_paisa,
        idempotency_key="idemp_replay_1",
    )
    res2 = setup2.provider.charge_mandate(
        mandate_token=setup2.primary_mandate.provider_mandate_token,
        amount_in_paisa=setup2.subscription.amount_in_paisa,
        idempotency_key="idemp_replay_1",
    )

    assert res1.success == res2.success
    assert res1.raw_error_code == res2.raw_error_code
    assert res1.raw_error_message == res2.raw_error_message


def test_insufficient_funds_liquidity_timing_scenario():
    """Verify failure outside liquidity window (Aug 28) and recovery inside window (Sept 2)."""
    setup = SyntheticScenarioGenerator.create_insufficient_funds_scenario(seed=42)
    mandate_token = setup.primary_mandate.provider_mandate_token
    amount = setup.subscription.amount_in_paisa

    # Attempt 1: August 28th (Outside Day 1-4 window) -> Fails with insufficient_funds
    res_aug28 = setup.provider.charge_mandate(
        mandate_token=mandate_token,
        amount_in_paisa=amount,
        idempotency_key="idemp_aug28",
    )
    assert res_aug28.success is False
    assert res_aug28.raw_error_code == "insufficient_funds"

    # Advance virtual clock to September 2nd (Inside Day 1-4 window)
    setup.clock.advance(days=5)  # Aug 28 + 5 days = Sept 2
    assert setup.clock.now().day == 2

    # Attempt 2: September 2nd -> Succeeded
    res_sep02 = setup.provider.charge_mandate(
        mandate_token=mandate_token,
        amount_in_paisa=amount,
        idempotency_key="idemp_sep02",
    )
    assert res_sep02.success is True
    assert res_sep02.provider_tx_id is not None
    assert res_sep02.provider_tx_id.startswith("pay_sim_")


def test_transient_issuer_glitch_and_immediate_retry():
    """Verify 1st attempt transient glitch (503) followed by successful immediate retry."""
    setup = SyntheticScenarioGenerator.create_transient_issuer_glitch_scenario(seed=42)
    mandate_token = setup.primary_mandate.provider_mandate_token
    amount = setup.subscription.amount_in_paisa

    # Attempt 1: Transient 503 bank error
    res1 = setup.provider.charge_mandate(
        mandate_token=mandate_token,
        amount_in_paisa=amount,
        idempotency_key="idemp_glitch_1",
    )
    assert res1.success is False
    assert res1.raw_error_code == "bank_technical_error"
    assert "503" in res1.raw_error_message

    # Attempt 2: Immediate retry on same rail -> Succeeded
    res2 = setup.provider.charge_mandate(
        mandate_token=mandate_token,
        amount_in_paisa=amount,
        idempotency_key="idemp_glitch_2",
    )
    assert res2.success is True
    assert res2.provider_tx_id is not None


def test_rail_degradation_and_alternate_path_switching():
    """Verify degraded rail failure and successful debit on alternate healthy payment method."""
    setup = SyntheticScenarioGenerator.create_rail_degradation_scenario(seed=42)
    sbi_mandate = setup.mandates[0]
    icici_mandate = setup.mandates[1]
    amount = setup.subscription.amount_in_paisa

    # Check rail health
    sbi_health = setup.provider.get_rail_health(IssuerBank.SBI, PaymentMethod.UPI_AUTOPAY)
    assert sbi_health.is_degraded is True
    assert sbi_health.success_rate < 0.65

    # Charge on degraded SBI rail -> Fails with issuer_down
    res_sbi = setup.provider.charge_mandate(
        mandate_token=sbi_mandate.provider_mandate_token,
        amount_in_paisa=amount,
        idempotency_key="idemp_sbi_degraded",
    )
    assert res_sbi.success is False
    assert res_sbi.raw_error_code == "issuer_down"

    # Switch path to healthy ICICI card mandate -> Succeeded
    res_icici = setup.provider.charge_mandate(
        mandate_token=icici_mandate.provider_mandate_token,
        amount_in_paisa=amount,
        idempotency_key="idemp_icici_healthy",
    )
    assert res_icici.success is True
    assert res_icici.provider_tx_id is not None


def test_revoked_mandate_failure():
    """Verify inactive/revoked mandate cannot be charged."""
    setup = SyntheticScenarioGenerator.create_revoked_mandate_scenario(seed=42)
    res = setup.provider.charge_mandate(
        mandate_token=setup.primary_mandate.provider_mandate_token,
        amount_in_paisa=setup.subscription.amount_in_paisa,
        idempotency_key="idemp_revoked",
    )
    assert res.success is False
    assert res.raw_error_code == "mandate_inactive"


def test_exceeded_mandate_limit():
    """Verify charging amount above registered max amount is rejected."""
    setup = SyntheticScenarioGenerator.create_insufficient_funds_scenario(seed=42)
    # Mandate max amount is ₹15,000 (1500000 paisa); attempt ₹20,000 (2000000 paisa)
    res = setup.provider.charge_mandate(
        mandate_token=setup.primary_mandate.provider_mandate_token,
        amount_in_paisa=2000000,
        idempotency_key="idemp_limit_exceeded",
    )
    assert res.success is False
    assert res.raw_error_code == "exceeded_limit"


def test_provider_idempotency_caching():
    """Verify repeating the same idempotency key returns exact identical result without re-executing."""
    setup = SyntheticScenarioGenerator.create_insufficient_funds_scenario(seed=42)
    mandate_token = setup.primary_mandate.provider_mandate_token
    amount = setup.subscription.amount_in_paisa

    res1 = setup.provider.charge_mandate(
        mandate_token=mandate_token,
        amount_in_paisa=amount,
        idempotency_key="idemp_duplicate_test",
    )
    res2 = setup.provider.charge_mandate(
        mandate_token=mandate_token,
        amount_in_paisa=amount,
        idempotency_key="idemp_duplicate_test",
    )

    assert res1 == res2


def test_provider_payment_link_generation():
    """Verify simulated payment link creation."""
    clock = SimulationClock()
    provider = SimulatedPaymentProvider(clock=clock, seed=42)
    link = provider.generate_payment_link(
        amount_in_paisa=499900,
        customer_id="cust_1029",
        description="Subscription Recovery Link",
        expires_in_seconds=3600,
    )
    assert link.link_id.startswith("plink_sim_")
    assert "rzp.io/i/" in link.short_url
    assert link.status == "active"
    assert link.expires_at > clock.now()
