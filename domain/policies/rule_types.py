from enum import Enum
from pydantic import BaseModel, Field
from typing import Optional, Any


class RuleCategory(str, Enum):
    """Explicit provenance taxonomy for all validation & safety rules."""
    REGULATORY_REQUIREMENT = "REGULATORY_REQUIREMENT"  # Official statutory directives (e.g. RBI/NPCI e-mandate rules)
    PROVIDER_RULE = "PROVIDER_RULE"                    # Gateway/Provider constraints (e.g. Razorpay token limits)
    MERCHANT_POLICY = "MERCHANT_POLICY"                # Merchant business risk policies (e.g. max retries, cooldowns)
    SIMULATION_POLICY = "SIMULATION_POLICY"            # Benchmark testbed assumptions (e.g. mock costs, virtual clock)


class EvaluatedRuleResult(BaseModel):
    """Deterministic record of an evaluated policy rule."""
    rule_id: str
    rule_name: str
    category: RuleCategory
    passed: bool
    description: str
    details: Optional[dict[str, Any]] = Field(default_factory=dict)
