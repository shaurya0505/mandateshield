import json
from datetime import datetime, timezone
from domain.models.payment_attempt import FailureCategory
from domain.models.recovery_case import RecoveryCase
from domain.models.strategy_proposal import StrategyReasonCode, PlannerSource
from domain.states.recovery_state import RecoveryAction, RecoveryState
from infrastructure.simulation.synthetic_scenario_generator import SyntheticScenarioGenerator
from infrastructure.llm.gemini_strategy_planner import GeminiStrategyPlanner
from services.ingestion.failure_normalizer import FailureNormalizer
from services.risk.revenue_risk_engine import RevenueRiskEngine
from services.signals.recovery_context_builder import RecoveryContextBuilder


def test_slice2_full_pipeline_strategy_planning():
    """
    End-to-End Slice 2 Strategy Planning Integration Test:
    Simulated Failure -> Normalization -> Risk Assessment -> Context Building -> AI Planning -> Proposal.
    
    Verifies:
    1. Proposal is generated cleanly with bounded reason codes.
    2. Zero financial mutations occur (NO PolicyAuthorization, NO debit charges).
    3. State remains safe in RECOVERY_ELIGIBLE.
    """
    setup = SyntheticScenarioGenerator.create_insufficient_funds_scenario(seed=42)

    # 1. Trigger simulated failure on Aug 28
    attempt_res = setup.provider.charge_mandate(
        mandate_token=setup.primary_mandate.provider_mandate_token,
        amount_in_paisa=setup.subscription.amount_in_paisa,
        idempotency_key="idemp_int_m5_01",
    )
    assert attempt_res.success is False

    # 2. Ingest and Normalize
    normalized = FailureNormalizer.normalize(attempt_res.raw_error_code, attempt_res.raw_error_message)
    assert normalized.category == FailureCategory.LIQUIDITY_FAILURE

    # 3. Assess Risk
    risk_assessment = RevenueRiskEngine.evaluate(
        subscription=setup.subscription,
        customer=setup.customer,
        mandate=setup.primary_mandate,
        failure_category=normalized.category,
    )

    # 4. Fetch Rail Health
    rail_health = setup.provider.get_rail_health(
        issuer_bank=setup.primary_mandate.issuer_bank,
        payment_method=setup.primary_mandate.payment_method,
    )

    # 5. Open Recovery Case
    case = RecoveryCase(
        id="case_m5_01",
        subscription_id=setup.subscription.id,
        customer_id=setup.customer.id,
        initial_attempt_id="att_m5_01",
        revenue_at_risk_in_paisa=risk_assessment.revenue_at_risk_in_paisa,
        status=RecoveryState.PAYMENT_FAILED,
    )
    case.transition_to(RecoveryState.RECOVERY_ELIGIBLE)
    assert case.status == RecoveryState.RECOVERY_ELIGIBLE

    # 6. Build Context
    past_dates = [
        datetime(2026, 6, 2, 10, 0, 0, tzinfo=timezone.utc),
        datetime(2026, 7, 1, 10, 0, 0, tzinfo=timezone.utc),
        datetime(2026, 8, 1, 10, 0, 0, tzinfo=timezone.utc),
    ]
    context = RecoveryContextBuilder.build(
        recovery_case=case,
        customer=setup.customer,
        subscription=setup.subscription,
        mandate=setup.primary_mandate,
        normalized_failure=normalized,
        risk_assessment=risk_assessment,
        rail_health=rail_health,
        customer_mandates=setup.mandates,
        historical_successful_dates=past_dates,
        current_time=setup.clock.now(),
    )

    # 7. AI Strategy Planning (Mocked Gemini invoker)
    def mock_gemini_invoker(system_prompt: str, user_prompt: str) -> str:
        return json.dumps({
            "action": "WAIT_AND_RETRY",
            "reason_codes": ["INSUFFICIENT_FUNDS", "HISTORICAL_PAYMENT_WINDOW"],
            "rationale": "Historical debits cluster on days 1-2. Delaying retry until upcoming settlement window.",
            "strategy_confidence": 0.86,
            "recommended_delay_seconds": 345600,
            "required_conditions": []
        })

    planner = GeminiStrategyPlanner(llm_invoker=mock_gemini_invoker)
    proposal = planner.propose_strategy(context)

    # Assertions on Proposal
    assert proposal.action == RecoveryAction.WAIT_AND_RETRY
    assert proposal.planner_source == PlannerSource.GEMINI_LLM
    assert StrategyReasonCode.HISTORICAL_PAYMENT_WINDOW in proposal.reason_codes
    assert proposal.strategy_confidence == 0.86
    assert proposal.recommended_delay_seconds == 345600
    assert proposal.recommended_retry_at is not None

    # Crucial Security Boundary Verification
    # 1. State machine has NOT transitioned to RECOVERY_ATTEMPTED
    assert case.status == RecoveryState.RECOVERY_ELIGIBLE
    # 2. Case has NO PolicyAuthorization record created by AI planner
    assert not hasattr(proposal, "authorized_action")
    assert not hasattr(proposal, "policy_verdict")
    # 3. Provider attempt count remains exactly 1 (initial failure only; no extra debit dispatched)
    assert len(setup.provider._attempt_ledger) == 1
