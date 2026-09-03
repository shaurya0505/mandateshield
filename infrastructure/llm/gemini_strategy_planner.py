import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional
from pydantic import BaseModel, Field, ValidationError

from domain.interfaces.strategy_planner import StrategyPlanner
from domain.models.recovery_context import RecoveryContext
from domain.models.strategy_proposal import StrategyProposal, StrategyReasonCode, PlannerSource
from domain.states.recovery_state import RecoveryAction
from services.ai.deterministic_fallback_planner import DeterministicFallbackPlanner
from infrastructure.llm.context_serializer import ContextSerializer


class RawLLMStrategyResponse(BaseModel):
    """Raw structured output expected from Gemini LLM."""
    action: RecoveryAction
    reason_codes: List[StrategyReasonCode] = Field(..., min_length=1)
    rationale: str = Field(..., min_length=5)
    strategy_confidence: float = Field(..., ge=0.0, le=1.0)
    recommended_delay_seconds: int = Field(default=0, ge=0)
    required_conditions: List[str] = Field(default_factory=list)


SYSTEM_PROMPT = """You are MandateShield's AI Recovery Strategy Advisor.
Your objective is to evaluate recurring payment failure context and recommend an optimal, safe recovery strategy.

IMPORTANT OPERATIONAL RULES:
1. You are an ADVISOR only. You do not authorize financial transactions, charge accounts, or mutate state.
2. You MUST select exactly ONE action from the following approved RecoveryAction enum values:
   - RETRY_NOW: Immediate re-attempt on same rail (transient gateway/issuer glitch on healthy rail).
   - WAIT_AND_RETRY: Schedule re-attempt during historical payment settlement window or after rail cooldown.
   - SWITCH_PAYMENT_PATH: Attempt debit using customer's alternative verified active payment method (ONLY if has_alternative_active_mandate is True).
   - GENERATE_PAYMENT_LINK: Issue a dynamic recovery payment link for interactive customer payment / auth friction.
   - SEND_RECOVERY_NUDGE: Dispatch customer notification to top up funds (when liquidity fails without clear historical window).
   - ESCALATE_TO_HUMAN: Route case to human operations (high-value VIP accounts, repeated 3+ failures, ambiguous errors).
   - STOP_RECOVERY: Terminate recovery immediately (mandate inactive, cancelled, revoked, or terminal error).

3. You MUST provide machine-readable reason codes chosen STRICTLY from:
   - HISTORICAL_PAYMENT_WINDOW
   - TRANSIENT_PROVIDER_FAILURE
   - RAIL_DEGRADATION
   - INSUFFICIENT_FUNDS
   - ACTIVE_ALTERNATIVE_MANDATE
   - MANDATE_INACTIVE
   - RETRY_LIMIT_APPROACHING
   - HIGH_VALUE_CASE
   - INSUFFICIENT_HISTORY
   - UNKNOWN_FAILURE
   - HUMAN_REVIEW_REQUIRED

4. Base your reasoning STRICTLY on the facts provided in the RecoveryContext JSON.
   - DO NOT claim to know customer salary or payday. Use 'historical payment timing window'.
   - DO NOT invent alternative payment paths if has_alternative_active_mandate is False.
   - DO NOT optimize solely for retry volume. Optimize for intelligent net recovery and customer trust. Knowing when to WAIT or STOP is paramount.

5. You MUST return STRICTLY valid JSON conforming to the following schema:
{
  "action": "<RecoveryAction>",
  "reason_codes": ["<StrategyReasonCode>"],
  "rationale": "<Concise 1-2 sentence explanation>",
  "strategy_confidence": <0.0 to 1.0 model confidence in this recommendation>,
  "recommended_delay_seconds": <integer seconds to wait, 0 for immediate actions>,
  "required_conditions": ["<any operational condition>"]
}
"""


class GeminiStrategyPlanner(StrategyPlanner):
    """
    LLM-powered Strategy Planner communicating with Gemini API via structured output.
    Wrapped with fail-closed safety: any network timeout, malformed JSON, or schema error
    automatically delegates to the DeterministicFallbackPlanner.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model_name: Optional[str] = None,
        timeout_seconds: float = 8.0,
        fallback_planner: Optional[DeterministicFallbackPlanner] = None,
        llm_invoker: Optional[Callable[[str, str], str]] = None,
    ):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        self.model_name = model_name or os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
        self.timeout_seconds = timeout_seconds
        self.fallback_planner = fallback_planner or DeterministicFallbackPlanner()
        self._llm_invoker = llm_invoker  # Allows mocking in unit tests

    def propose_strategy(self, context: RecoveryContext) -> StrategyProposal:
        """
        Calls the Gemini model with sanitized RecoveryContext and parses structured output.
        Fails safely to DeterministicFallbackPlanner if any error or invalid output occurs.
        """
        serialized_context = ContextSerializer.serialize_for_ai(context)

        # 1. Check for API key or mock invoker availability
        if not self.api_key and not self._llm_invoker:
            return self.fallback_planner.propose_strategy(
                context, fallback_reason="GEMINI_API_KEY not configured. Used deterministic fallback."
            )

        # 2. Invoke LLM
        try:
            if self._llm_invoker:
                raw_response_text = self._llm_invoker(SYSTEM_PROMPT, serialized_context)
            else:
                raw_response_text = self._call_gemini_api(SYSTEM_PROMPT, serialized_context)

            # 3. Parse and Validate JSON
            parsed_json = self._extract_json(raw_response_text)
            validated_response = RawLLMStrategyResponse.model_validate(parsed_json)

            # 4. Contextual Guardrail Validations
            # If model proposes SWITCH_PAYMENT_PATH but context has no alternative mandate, reject
            if (
                validated_response.action == RecoveryAction.SWITCH_PAYMENT_PATH
                and not context.has_alternative_active_mandate
            ):
                return self.fallback_planner.propose_strategy(
                    context,
                    fallback_reason="Model proposed SWITCH_PAYMENT_PATH without active alternative mandate.",
                )

            # Calculate recommended retry timestamp if delay is provided
            delay_sec = validated_response.recommended_delay_seconds
            retry_at = context.current_timestamp + timedelta(seconds=delay_sec) if delay_sec > 0 else None

            return StrategyProposal(
                proposal_id=f"prop_gem_{uuid.uuid4().hex[:10]}",
                recovery_case_id=context.recovery_case_id,
                subscription_id=context.subscription_id,
                action=validated_response.action,
                reason_codes=validated_response.reason_codes,
                rationale=validated_response.rationale,
                strategy_confidence=validated_response.strategy_confidence,
                recommended_delay_seconds=delay_sec,
                recommended_retry_at=retry_at,
                required_conditions=validated_response.required_conditions,
                planner_source=PlannerSource.GEMINI_LLM,
                fallback_reason=None,
                generated_at=context.current_timestamp,
            )

        except (ValidationError, json.JSONDecodeError) as err:
            return self.fallback_planner.propose_strategy(
                context, fallback_reason=f"LLM output schema validation failed: {str(err)[:100]}"
            )
        except Exception as err:
            return self.fallback_planner.propose_strategy(
                context, fallback_reason=f"LLM invocation failed: {str(err)[:100]}"
            )

    def _call_gemini_api(self, system_prompt: str, user_prompt: str) -> str:
        """Invokes upstream Google GenAI SDK with structured response constraints."""
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=self.api_key)
        response = client.models.generate_content(
            model=self.model_name,
            contents=[user_prompt],
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                response_mime_type="application/json",
            ),
        )
        return response.text

    @staticmethod
    def _extract_json(text: str) -> Dict[str, Any]:
        """Extracts JSON from response string even if wrapped in markdown blocks."""
        cleaned = text.strip()
        if cleaned.startswith("```json"):
            cleaned = cleaned[7:]
        if cleaned.startswith("```"):
            cleaned = cleaned[3:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        return json.loads(cleaned.strip())
