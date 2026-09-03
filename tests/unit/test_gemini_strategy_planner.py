import json
import pytest
from datetime import datetime, timezone
from domain.models.recovery_context import RecoveryContext
from domain.models.strategy_proposal import StrategyReasonCode, PlannerSource
from domain.states.recovery_state import RecoveryAction
from infrastructure.llm.context_serializer import ContextSerializer
from infrastructure.llm.gemini_strategy_planner import GeminiStrategyPlanner
from tests.unit.test_deterministic_fallback_planner import _build_test_context


def test_gemini_valid_structured_response_parsing():
    """Verify clean parsing of valid structured Gemini output."""
    context = _build_test_context(raw_error="insufficient_funds")

    def mock_invoker(system_prompt: str, user_prompt: str) -> str:
        return json.dumps({
            "action": "WAIT_AND_RETRY",
            "reason_codes": ["INSUFFICIENT_FUNDS", "HISTORICAL_PAYMENT_WINDOW"],
            "rationale": "Customer payment cluster indicates settlement at beginning of month.",
            "strategy_confidence": 0.88,
            "recommended_delay_seconds": 345600,
            "required_conditions": ["cooldown_enforced"]
        })

    planner = GeminiStrategyPlanner(llm_invoker=mock_invoker)
    proposal = planner.propose_strategy(context)

    assert proposal.action == RecoveryAction.WAIT_AND_RETRY
    assert proposal.planner_source == PlannerSource.GEMINI_LLM
    assert proposal.strategy_confidence == 0.88
    assert proposal.recommended_delay_seconds == 345600
    assert proposal.fallback_reason is None
    assert StrategyReasonCode.HISTORICAL_PAYMENT_WINDOW in proposal.reason_codes


def test_gemini_markdown_wrapped_json_parsing():
    """Verify parser extracts JSON wrapped inside markdown code blocks."""
    context = _build_test_context(raw_error="bank_technical_error")

    def mock_invoker(system_prompt: str, user_prompt: str) -> str:
        return """```json
        {
            "action": "RETRY_NOW",
            "reason_codes": ["TRANSIENT_PROVIDER_FAILURE"],
            "rationale": "Transient 503 bank error on healthy active rail.",
            "strategy_confidence": 0.92,
            "recommended_delay_seconds": 0,
            "required_conditions": []
        }
        ```"""

    planner = GeminiStrategyPlanner(llm_invoker=mock_invoker)
    proposal = planner.propose_strategy(context)

    assert proposal.action == RecoveryAction.RETRY_NOW
    assert proposal.planner_source == PlannerSource.GEMINI_LLM


def test_gemini_malformed_json_triggers_safe_fallback():
    """Verify unparseable JSON from LLM gracefully delegates to conservative deterministic fallback."""
    context = _build_test_context(raw_error="bank_technical_error")

    def mock_broken_invoker(system_prompt: str, user_prompt: str) -> str:
        return "Sorry, I am an AI and cannot process this right now."

    planner = GeminiStrategyPlanner(llm_invoker=mock_broken_invoker)
    proposal = planner.propose_strategy(context)

    assert proposal.planner_source == PlannerSource.DETERMINISTIC_FALLBACK
    assert proposal.fallback_reason is not None
    assert "validation failed" in proposal.fallback_reason or "JSON" in proposal.fallback_reason
    assert proposal.action in (RecoveryAction.RETRY_NOW, RecoveryAction.WAIT_AND_RETRY, RecoveryAction.ESCALATE_TO_HUMAN)


def test_gemini_unknown_action_triggers_safe_fallback():
    """Verify hallucinated/unknown recovery action is rejected and falls back safely."""
    context = _build_test_context(raw_error="insufficient_funds")

    def mock_hallucinated_invoker(system_prompt: str, user_prompt: str) -> str:
        return json.dumps({
            "action": "CHARGE_CARD_THREE_TIMES_IMMEDIATELY",
            "reason_codes": ["INSUFFICIENT_FUNDS"],
            "rationale": "Aggressively retry card.",
            "strategy_confidence": 0.99,
            "recommended_delay_seconds": 0
        })

    planner = GeminiStrategyPlanner(llm_invoker=mock_hallucinated_invoker)
    proposal = planner.propose_strategy(context)

    assert proposal.planner_source == PlannerSource.DETERMINISTIC_FALLBACK
    assert proposal.fallback_reason is not None


def test_gemini_hallucinated_alternative_path_guardrail():
    """Verify guardrail rejects SWITCH_PAYMENT_PATH if context has no alternative mandate."""
    # Context has has_alt_mandate=False
    context = _build_test_context(raw_error="issuer_down", has_alt_mandate=False)

    def mock_invoker(system_prompt: str, user_prompt: str) -> str:
        return json.dumps({
            "action": "SWITCH_PAYMENT_PATH",
            "reason_codes": ["RAIL_DEGRADATION", "ACTIVE_ALTERNATIVE_MANDATE"],
            "rationale": "Switch to alternative payment method.",
            "strategy_confidence": 0.85,
            "recommended_delay_seconds": 0
        })

    planner = GeminiStrategyPlanner(llm_invoker=mock_invoker)
    proposal = planner.propose_strategy(context)

    # Must be intercepted by contextual guardrail and delegated to fallback
    assert proposal.planner_source == PlannerSource.DETERMINISTIC_FALLBACK
    assert "SWITCH_PAYMENT_PATH without active alternative mandate" in proposal.fallback_reason


def test_gemini_api_timeout_triggers_safe_fallback():
    """Verify network/timeout exception triggers deterministic fallback."""
    context = _build_test_context(raw_error="insufficient_funds")

    def mock_timeout_invoker(system_prompt: str, user_prompt: str) -> str:
        raise TimeoutError("Gemini API connection timed out after 8.0s")

    planner = GeminiStrategyPlanner(llm_invoker=mock_timeout_invoker)
    proposal = planner.propose_strategy(context)

    assert proposal.planner_source == PlannerSource.DETERMINISTIC_FALLBACK
    assert "LLM invocation failed" in proposal.fallback_reason


def test_context_serializer_sanitization():
    """Verify serialized JSON excludes sensitive provider keys or internal objects."""
    context = _build_test_context(raw_error="insufficient_funds")
    serialized = ContextSerializer.serialize_for_ai(context)
    data = json.loads(serialized)

    assert "case_id" in data
    assert "amount_in_paisa" in data
    assert "amount_in_inr" in data
    assert data["amount_in_inr"] == 4999.0
    assert "api_key" not in data
    assert "secret" not in data
    assert "db_session" not in data
