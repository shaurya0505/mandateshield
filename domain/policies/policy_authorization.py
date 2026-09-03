from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional, List
from pydantic import BaseModel, Field, ConfigDict
from domain.states.recovery_state import RecoveryAction
from domain.policies.rule_types import EvaluatedRuleResult


class PolicyVerdict(str, Enum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    ESCALATED = "ESCALATED"


class PolicyAuthorization(BaseModel):
    """
    Deterministic domain record generated exclusively by Policy Guardian upon approving a proposal.
    The RecoveryExecutor requires a valid APPROVED PolicyAuthorization before executing any financial action.
    """
    model_config = ConfigDict(frozen=True)

    auth_id: str = Field(..., description="Unique authorization ID (e.g. auth_8492)")
    case_id: str = Field(...)
    decision_id: str = Field(...)
    authorized_action: RecoveryAction
    verdict: PolicyVerdict
    evaluated_rules: List[EvaluatedRuleResult] = Field(default_factory=list)
    rejection_reasons: List[str] = Field(default_factory=list)
    valid_until: datetime
    execution_parameters: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def is_valid_for_execution(self, current_time: Optional[datetime] = None) -> bool:
        """Verifies that authorization is approved and not expired."""
        now = current_time or datetime.now(timezone.utc)
        return self.verdict == PolicyVerdict.APPROVED and now <= self.valid_until
