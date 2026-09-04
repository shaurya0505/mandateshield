import json
from datetime import datetime, timezone
from domain.models.payment_attempt import FailureCategory
from domain.models.recovery_case import RecoveryCase
from domain.models.policy_authorization import PolicyVerdict, PolicyAuthorization
from domain.models.execution_result import ExecutionStatus
from domain.states.recovery_state import RecoveryAction, RecoveryState
from infrastructure.simulation.synthetic_scenario_generator import SyntheticScenarioGenerator
from infrastructure.llm.gemini_strategy_planner import GeminiStrategyPlanner
from services.ingestion.failure_normalizer import FailureNormalizer
from services.risk.revenue_risk_engine import RevenueRiskEngine
from services.signals.recovery_context_builder import RecoveryContextBuilder
from services.policy.policy_guardian import PolicyGuardian
from services.executor.recovery_executor import RecoveryExecutor


def test_slice3_full_end_to_end_recovery_pipeline():
    """
    Complete End-to-End Slice 3 Integration Test:
    Simulated Failure -> Normalizer -> Risk Engine -> Recovery Context ->
    AI Strategy Planner -> Policy Guardian -> Policy Authorization ->
    Recovery Executor -> Payment Provider -> Terminal State.
    """
    # 1. Setup scenario: Transient glitch on healthy HDFC mandate
    setup = SyntheticScenarioGenerator.create_transient_issuer_glitch_scenario(seed=42)

    # 2. Ingestion: Initial attempt failed due to transient gateway glitch
    initial_res = setup.provider.charge_mandate(
        mandate_token=setup.primary_mandate.provider_mandate_token,
        amount_in_paisa=setup.subscription.amount_in_paisa,
        idempotency_key="idemp_init_m7_01",
    )
    assert initial_res.success is False

    # 3. Normalization & Risk Evaluation
    normalized = FailureNormalizer.normalize(initial_res.raw_error_code, initial_res.raw_error_message)
    risk_assessment = RevenueRiskEngine.evaluate(
        subscription=setup.subscription,
        customer=setup.customer,
        mandate=setup.primary_mandate,
        failure_category=normalized.category,
    )
    rail_health = setup.provider.get_rail_health(
        issuer_bank=setup.primary_mandate.issuer_bank,
        payment_method=setup.primary_mandate.payment_method,
    )

    # 4. Initialize Recovery Case
    case = RecoveryCase(
        id="case_m7_pipeline_01",
        subscription_id=setup.subscription.id,
        customer_id=setup.customer.id,
        initial_attempt_id="att_m7_init_01",
        revenue_at_risk_in_paisa=risk_assessment.revenue_at_risk_in_paisa,
        status=RecoveryState.PAYMENT_FAILED,
    )
    case.transition_to(RecoveryState.RECOVERY_ELIGIBLE)

    # 5. Build Context Envelope
    context = RecoveryContextBuilder.build(
        recovery_case=case,
        customer=setup.customer,
        subscription=setup.subscription,
        mandate=setup.primary_mandate,
        normalized_failure=normalized,
        risk_assessment=risk_assessment,
        rail_health=rail_health,
        customer_mandates=setup.mandates,
        current_time=setup.clock.now(),
    )

    # 6. AI Strategy Planner proposes RETRY_NOW
    def mock_gemini_invoker(system_prompt: str, user_prompt: str) -> str:
        return json.dumps({
            "action": "RETRY_NOW",
            "reason_codes": ["TRANSIENT_PROVIDER_FAILURE"],
            "rationale": "Transient bank glitch on healthy mandate. Immediate retry recommended.",
            "strategy_confidence": 0.94,
            "recommended_delay_seconds": 0,
            "required_conditions": []
        })

    planner = GeminiStrategyPlanner(llm_invoker=mock_gemini_invoker)
    proposal = planner.propose_strategy(context)
    assert proposal.action == RecoveryAction.RETRY_NOW

    # 7. Policy Guardian evaluates and authorizes
    guardian = PolicyGuardian()
    evaluation = guardian.evaluate(context, proposal, case_status=case.status)
    assert evaluation.is_approved is True
    assert evaluation.authorization is not None
    auth = evaluation.authorization

    # 8. Recovery Executor executes authorized debit
    executor = RecoveryExecutor()
    exec_result = executor.execute(
        authorization=auth,
        case=case,
        customer=setup.customer,
        subscription=setup.subscription,
        mandate=setup.primary_mandate,
        provider=setup.provider,
        current_time=setup.clock.now(),
    )

    # Invariant Validations
    assert exec_result.success is True
    assert exec_result.status == ExecutionStatus.SUCCESS
    assert exec_result.amount_in_paisa == setup.subscription.amount_in_paisa
    assert exec_result.operational_cost_in_paisa == 500  # ₹5.00
    assert case.status == RecoveryState.RECOVERED
    assert case.recovered_amount_in_paisa == setup.subscription.amount_in_paisa
    assert case.recovery_cost_in_paisa == 500
    assert case.total_attempts == 1

    # 9. Idempotent Replay Validation
    # Calling executor again with the same authorization must NOT produce another provider charge
    replay_result = executor.execute(
        authorization=auth,
        case=case,
        customer=setup.customer,
        subscription=setup.subscription,
        mandate=setup.primary_mandate,
        provider=setup.provider,
        current_time=setup.clock.now(),
    )
    assert replay_result.success is True
    assert replay_result.status == ExecutionStatus.ALREADY_CONSUMED
    assert replay_result.operational_cost_in_paisa == 0
    # Ledger count is exactly 2: the initial simulated failure (step 2) and the single authorized recovery debit (step 8)
    assert len(setup.provider._attempt_ledger) == 2
