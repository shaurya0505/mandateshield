from typing import Optional
from fastapi import APIRouter, Query, HTTPException
from pydantic import BaseModel, Field

from api.demo_service import DemoService, DemoExecutionReport
from services.evaluation.batch_evaluator import BatchEvaluator
from domain.models.evaluation import BatchEvaluationResult

router = APIRouter(prefix="/api", tags=["Command Center"])
demo_service = DemoService()


class RunEvaluationRequest(BaseModel):
    seed: int = Field(default=42, description="Deterministic scenario seed")
    scenario_count: int = Field(default=20, ge=6, le=100, description="Total synthetic scenarios to evaluate")


@router.get("/dashboard/stats")
def get_dashboard_stats():
    """Returns high-level recovery performance and active cases."""
    return demo_service.get_dashboard_summary()


@router.post("/demo/hero-scenario", response_model=DemoExecutionReport)
def run_hero_scenario():
    """Runs the primary Hero Scenario: Liquidity window recovery for Rahul Mehta (₹4,999)."""
    return demo_service.run_hero_scenario()


@router.post("/demo/safety-block", response_model=DemoExecutionReport)
def run_safety_block():
    """Runs the Safety Policy Guardrail Scenario: AI RETRY_NOW blocked on revoked mandate."""
    return demo_service.run_safety_block_scenario()


@router.post("/demo/webhook-resilience", response_model=DemoExecutionReport)
def run_webhook_resilience():
    """Runs the Webhook Reconciliation & Deduplication Scenario."""
    return demo_service.run_webhook_resilience_scenario()


@router.post("/demo/reset")
def reset_demo():
    """Resets the demo environment to initial state."""
    return demo_service.reset_state()


@router.post("/evaluation/run", response_model=BatchEvaluationResult)
def run_batch_evaluation(request: Optional[RunEvaluationRequest] = None):
    """Executes a paired counterfactual batch evaluation across all 3 policies."""
    seed = request.seed if request else 42
    scenario_count = request.scenario_count if request else 20
    evaluator = BatchEvaluator()
    return evaluator.evaluate(seed=seed, scenario_count=scenario_count)
