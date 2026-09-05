from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional
from pydantic import BaseModel, Field, ConfigDict
from domain.states.recovery_state import RecoveryAction, RecoveryState


class EvaluationPolicy(str, Enum):
    """The three evaluation policies compared in paired counterfactual simulations."""
    NO_RECOVERY = "NO_RECOVERY"        # Zero intervention after initial debit failure
    FIXED_RETRY = "FIXED_RETRY"        # Naive schedule-based retry without contextual intelligence
    MANDATESHIELD = "MANDATESHIELD"    # Context-aware intelligent recovery with Policy Guardian


class ScenarioOutcome(BaseModel):
    """Outcome of evaluating a single policy against a single scenario."""
    model_config = ConfigDict(frozen=True)

    scenario_id: str
    scenario_name: str
    policy: EvaluationPolicy
    initial_amount_at_risk_in_paisa: int = Field(..., gt=0)
    gross_recovered_amount_in_paisa: int = Field(default=0, ge=0)
    operational_cost_in_paisa: int = Field(default=0, ge=0)
    net_recovered_amount_in_paisa: int = Field(default=0)
    is_recovered: bool
    final_case_state: RecoveryState
    total_retries: int = Field(default=0, ge=0)
    total_nudges: int = Field(default=0, ge=0)
    unnecessary_retries: int = Field(default=0, ge=0)
    actions_taken: List[RecoveryAction] = Field(default_factory=list)
    simulated_duration_seconds: int = Field(default=0, ge=0)


class PairedScenarioResult(BaseModel):
    """Paired counterfactual outcomes for one identical scenario across all three policies."""
    model_config = ConfigDict(frozen=True)

    scenario_id: str
    scenario_name: str
    failure_mode: str
    no_recovery: ScenarioOutcome
    fixed_retry: ScenarioOutcome
    mandateshield: ScenarioOutcome


class PolicyMetricSummary(BaseModel):
    """Aggregated financial and operational metrics for a specific policy across a batch."""
    model_config = ConfigDict(frozen=True)

    policy: EvaluationPolicy
    eligible_cases: int = Field(..., ge=0)
    recovered_cases: int = Field(..., ge=0)
    recovery_rate: float = Field(..., ge=0.0, le=1.0, description="Case-count recovery rate: recovered_cases / eligible_cases")
    total_revenue_at_risk_in_paisa: int = Field(..., ge=0)
    gross_recovered_amount_in_paisa: int = Field(..., ge=0)
    net_recovered_amount_in_paisa: int = Field(...)
    value_weighted_recovery_rate: float = Field(..., ge=0.0, le=1.0, description="Monetary recovery rate: gross_recovered / total_at_risk")
    total_operational_cost_in_paisa: int = Field(..., ge=0)
    total_retries: int = Field(..., ge=0)
    total_nudges: int = Field(..., ge=0)
    unnecessary_retries_count: int = Field(..., ge=0)
    customer_contact_index: float = Field(..., ge=0.0, description="Internal harassment/friction index: retries*1.0 + nudges*1.5 + escalations*0.5")
    action_distribution: Dict[RecoveryAction, int] = Field(default_factory=dict)


class LiftMetrics(BaseModel):
    """Comparative lift metrics measuring MandateShield's performance vs baselines."""
    model_config = ConfigDict(frozen=True)

    gross_recovery_lift_vs_no_recovery_in_paisa: int
    net_recovery_lift_vs_no_recovery_in_paisa: int
    gross_recovery_lift_vs_fixed_retry_in_paisa: int
    net_recovery_lift_vs_fixed_retry_in_paisa: int
    percentage_lift_vs_no_recovery: Optional[float] = Field(default=None, description="Percentage lift in gross recovery vs NO_RECOVERY (None if baseline is 0)")
    percentage_lift_vs_fixed_retry: Optional[float] = Field(default=None, description="Percentage lift in gross recovery vs FIXED_RETRY (None if baseline is 0)")
    recovery_rate_lift_vs_fixed_retry: float = Field(..., description="Absolute percentage point difference in recovery rate")
    retries_avoided_vs_fixed_retry: int = Field(..., description="Number of unnecessary retry attempts eliminated by MandateShield")
    contact_reduction_vs_fixed_retry: float = Field(..., description="Reduction in customer contact/harassment index")


class BatchEvaluationResult(BaseModel):
    """Complete, reproducible batch benchmark evaluation report."""
    model_config = ConfigDict(frozen=True)

    evaluation_id: str = Field(..., description="Unique evaluation run identifier")
    seed: int = Field(...)
    scenario_count: int = Field(..., gt=0)
    policy_summaries: Dict[EvaluationPolicy, PolicyMetricSummary]
    lift_metrics: LiftMetrics
    paired_results: List[PairedScenarioResult] = Field(default_factory=list)
    evaluated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
