import json
from datetime import datetime, timezone
from domain.models.payment_attempt import FailureCategory
from domain.models.recovery_case import RecoveryCase
from domain.models.policy_authorization import PolicyVerdict, PolicyAuthorization
from domain.states.recovery_state import RecoveryAction, RecoveryState
from infrastructure.simulation.synthetic_scenario_generator import SyntheticScenarioGenerator
from infrastructure.llm.gemini_strategy_planner import GeminiStrategyPlanner
from services.ingestion.failure_normalizer import FailureNormalizer
from services.risk.revenue_risk_engine import RevenueRiskEngine
from services.signals.recovery_context_builder import RecoveryContextBuilder
from services.policy.policy_guardian import PolicyGuardian


def test_slice2_boundary_ai_proposes_guardian_authorizes():
    """
    Slice 2 Full Boundary Integration Test:
    Simulated Failure -> Ingestion -> Risk Engine -> Context Building -> AI Planner -> Policy Guardian.
    
    Proves:
    1. AI Planner proposes an action.
    2. Policy Guardian evaluates against deterministic rules.
    3. Approved proposal receives a deterministic PolicyAuthorization.
    4. ZERO payment provider calls occur.
    5. ZERO state machine transitions occur from PolicyGuardian evaluation.
    """
    setup = SyntheticScenarioGenerator.create_insufficient_funds_scenario(seed=42)

    # 1. Initial simulated debit failure on Aug 28
    attempt_res = setup.provider.charge_mandate(
        mandate_token=setup.primary_mandate.provider_mandate_token,
        amount_in_paisa=setup.subscription.amount_in_paisa,
        idempotency_key="idemp_int_m6_01",
    )
    assert attempt_res.success is False

    # 2. Failure Normalization
    normalized = FailureNormalizer.normalize(attempt_res.raw_error_code, attempt_res.raw_error_message)

    # 3. Revenue Risk Assessment
    risk_assessment = RevenueRiskEngine.evaluate(
        subscription=setup.subscription,
        customer=setup.customer,
        mandate=setup.primary_mandate,
        failure_category=normalized.category,
    )

    # 4. Rail Health
    rail_health = setup.provider.get_rail_health(
        issuer_bank=setup.primary_mandate.issuer_bank,
        payment_method=setup.primary_mandate.payment_method,
    )

    # 5. Open Recovery Case
    case = RecoveryCase(
        id="case_m6_01",
        subscription_id=setup.subscription.id,
        customer_id=setup.customer.id,
        initial_attempt_id="att_m6_01",
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

    # 7. AI Strategy Proposal (WAIT_AND_RETRY proposed)
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
    assert proposal.action == RecoveryAction.WAIT_AND_RETRY

    # 8. Policy Guardian Evaluation
    guardian = PolicyGuardian()
    evaluation = guardian.evaluate(context, proposal, case_status=case.status)

    # Assertions on Policy Guardian Output
    assert evaluation.is_approved is True
    assert evaluation.verdict == PolicyVerdict.APPROVED
    assert evaluation.authorization is not None
    assert isinstance(evaluation.authorization, PolicyAuthorization)
    assert evaluation.authorization.authorized_action == RecoveryAction.WAIT_AND_RETRY
    assert evaluation.authorization.decision_id == proposal.proposal_id
    assert evaluation.authorization.is_valid_for_execution(context.current_timestamp) is True

    # Critical Separation of Concerns & Security Verification:
    # 1. State machine has NOT transitioned merely from policy evaluation
    assert case.status == RecoveryState.RECOVERY_ELIGIBLE
    # 2. Payment Provider has NOT been called for recovery debit
    assert len(setup.provider._attempt_ledger) == 1
