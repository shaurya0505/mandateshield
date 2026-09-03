from datetime import datetime, timezone
from typing import List, Optional
from pydantic import BaseModel, Field, ConfigDict
from domain.states.recovery_state import RecoveryAction
from domain.policies.rule_types import EvaluatedRuleResult
from domain.policies.policy_authorization import PolicyAuthorization, PolicyVerdict


class PolicyEvaluation(BaseModel):
    """
    Immutable, fully auditable record of a Policy Guardian evaluation pass.
    Records every evaluated rule, its provenance, pass/fail status, and the final verdict.
    """
    model_config = ConfigDict(frozen=True)

    evaluation_id: str = Field(..., description="Unique evaluation ID (e.g. eval_7192)")
    recovery_case_id: str = Field(...)
    proposal_id: str = Field(...)
    evaluated_action: RecoveryAction
    verdict: PolicyVerdict
    is_approved: bool
    evaluated_rules: List[EvaluatedRuleResult] = Field(default_factory=list)
    rejection_reasons: List[str] = Field(default_factory=list)
    evaluated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    authorization: Optional[PolicyAuthorization] = Field(
        default=None,
        description="Populated strictly when verdict is APPROVED; None otherwise.",
    )
