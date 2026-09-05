from datetime import datetime, timezone
import pytest

from domain.models.customer import Customer
from domain.models.mandate import Mandate, MandateStatus, PaymentMethod, IssuerBank
from domain.models.subscription import Subscription, BillingCycle
from domain.models.evaluation import EvaluationPolicy
from domain.states.recovery_state import RecoveryAction, RecoveryState
from infrastructure.simulation.simulation_clock import SimulationClock
from infrastructure.simulation.simulated_payment_provider import SimulatedPaymentProvider
from services.evaluation.baselines import ScenarioRunner


def _create_test_fixture():
    clock = SimulationClock(datetime(2026, 8, 28, 10, 0, 0, tzinfo=timezone.utc))
    provider = SimulatedPaymentProvider(clock=clock, seed=42)
    cust = Customer(id="c_test_01", name="Eval Test Cust", email="eval@example.com")
    mnd_primary = Mandate(
        id="mnd_p_01",
        customer_id=cust.id,
        provider_mandate_token="rzp_tok_p_01",
        payment_method=PaymentMethod.CARD_MANDATE,
        issuer_bank=IssuerBank.HDFC,
        status=MandateStatus.ACTIVE,
        max_amount_in_paisa=5000000,
    )
    mnd_alt = Mandate(
        id="mnd_a_01",
        customer_id=cust.id,
        provider_mandate_token="rzp_tok_a_01",
        payment_method=PaymentMethod.UPI_AUTOPAY,
        issuer_bank=IssuerBank.ICICI,
        status=MandateStatus.ACTIVE,
        max_amount_in_paisa=5000000,
    )
    provider.register_mandate(mnd_primary, liquidity_window_days=(1, 4))
    provider.register_mandate(mnd_alt, liquidity_window_days=(1, 4))
    sub = Subscription(
        id="sub_test_01",
        customer_id=cust.id,
        current_mandate_id=mnd_primary.id,
        amount_in_paisa=499900,
        billing_cycle=BillingCycle.MONTHLY,
        next_billing_at=clock.now(),
    )
    past_dates = [
        datetime(2026, 6, 2, 10, 0, 0, tzinfo=timezone.utc),
        datetime(2026, 7, 1, 10, 0, 0, tzinfo=timezone.utc),
        datetime(2026, 8, 1, 10, 0, 0, tzinfo=timezone.utc),
    ]
    return cust, [mnd_primary, mnd_alt], mnd_primary, sub, provider, clock, past_dates


def test_no_recovery_runner():
    """Verify NO_RECOVERY policy takes zero recovery actions and recovers 0 paisa."""
    cust, mnds, mnd, sub, prov, clk, _ = _create_test_fixture()

    outcome = ScenarioRunner.run_no_recovery(
        scenario_id="scen_no_rec_01",
        scenario_name="No Recovery Test",
        customer=cust,
        subscription=sub,
        mandate=mnd,
        provider=prov,
        clock=clk,
    )

    assert outcome.policy == EvaluationPolicy.NO_RECOVERY
    assert outcome.is_recovered is False
    assert outcome.gross_recovered_amount_in_paisa == 0
    assert outcome.operational_cost_in_paisa == 0
    assert outcome.total_retries == 0
    assert outcome.actions_taken == []


def test_fixed_retry_runner():
    """Verify FIXED_RETRY blindly attempts up to 3 retries at 24h intervals."""
    cust, mnds, mnd, sub, prov, clk, _ = _create_test_fixture()

    outcome = ScenarioRunner.run_fixed_retry(
        scenario_id="scen_fixed_01",
        scenario_name="Fixed Retry Test",
        customer=cust,
        subscription=sub,
        mandate=mnd,
        provider=prov,
        clock=clk,
    )

    assert outcome.policy == EvaluationPolicy.FIXED_RETRY
    # On Aug 28, retries at Aug 29, Aug 30, Aug 31 all fail due to insufficient funds (outside Day 1-4)
    assert outcome.total_retries == 3
    assert outcome.operational_cost_in_paisa == 1500  # 3 * ₹5.00
    assert outcome.is_recovered is False
    assert outcome.unnecessary_retries == 3


def test_mandateshield_runner_intelligent_wait_and_recover():
    """Verify MANDATESHIELD schedules WAIT_AND_RETRY to optimal window and successfully recovers."""
    cust, mnds, mnd, sub, prov, clk, past_dates = _create_test_fixture()

    outcome = ScenarioRunner.run_mandateshield(
        scenario_id="scen_ms_01",
        scenario_name="MandateShield Test",
        customer=cust,
        subscription=sub,
        mandates=mnds,
        primary_mandate=mnd,
        provider=prov,
        clock=clk,
        historical_successful_dates=past_dates,
    )

    assert outcome.policy == EvaluationPolicy.MANDATESHIELD
    # Proposes WAIT_AND_RETRY (waits until Sept 1/2 window), then executes RETRY_NOW successfully
    assert outcome.is_recovered is True
    assert outcome.gross_recovered_amount_in_paisa == 499900
    assert outcome.operational_cost_in_paisa == 500  # Only 1 debit fee on successful attempt
    assert outcome.net_recovered_amount_in_paisa == 499400
    assert outcome.total_retries == 1
    assert outcome.unnecessary_retries == 0
    assert RecoveryAction.WAIT_AND_RETRY in outcome.actions_taken
    assert RecoveryAction.RETRY_NOW in outcome.actions_taken
