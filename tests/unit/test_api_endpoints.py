import pytest
from fastapi.testclient import TestClient
from api.main import app

client = TestClient(app)


def test_health_check_endpoint():
    """Verify health check endpoint returns healthy status."""
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json() == {"status": "healthy", "service": "MandateShield"}


def test_dashboard_stats_endpoint():
    """Verify dashboard stats returns total revenue at risk and case summaries."""
    res = client.get("/api/dashboard/stats")
    assert res.status_code == 200
    data = res.json()
    assert "total_revenue_at_risk_formatted" in data
    assert "total_recovered_revenue_formatted" in data
    assert "cases" in data
    assert len(data["cases"]) >= 4


def test_hero_scenario_endpoint():
    """Verify hero liquidity timing recovery flow executes end-to-end via API."""
    res = client.post("/api/demo/hero-scenario")
    assert res.status_code == 200
    data = res.json()
    assert data["customer_name"] == "Rahul Mehta"
    assert data["amount_in_paisa"] == 499900
    assert data["policy_decision"] == "APPROVED"
    assert data["final_case_state"] == "RECOVERED"
    assert data["recovered_amount_in_paisa"] == 499900
    assert len(data["timeline"]) >= 7


def test_safety_block_endpoint():
    """Verify safety guardrail endpoint blocks AI retry proposal on revoked mandate."""
    res = client.post("/api/demo/safety-block")
    assert res.status_code == 200
    data = res.json()
    assert data["customer_name"] == "Deepa Rao"
    assert data["policy_decision"] == "BLOCKED"
    assert data["final_case_state"] == "STOPPED"
    assert data["recovered_amount_in_paisa"] == 0


def test_webhook_resilience_endpoint():
    """Verify webhook resilience endpoint demonstrates async settlement & duplicate detection."""
    res = client.post("/api/demo/webhook-resilience")
    assert res.status_code == 200
    data = res.json()
    assert data["final_case_state"] == "RECOVERED"
    # Timeline should include gateway timeout, async webhook, and duplicate replay
    stages = [evt["stage"] for evt in data["timeline"]]
    assert "GATEWAY_TIMEOUT" in stages
    assert "WEBHOOK_INGESTION" in stages
    assert "DEDUPLICATION_REPLAY" in stages


def test_evaluation_run_endpoint():
    """Verify batch evaluation API executes deterministic counterfactual benchmark."""
    res = client.post("/api/evaluation/run", json={"seed": 42, "scenario_count": 12})
    assert res.status_code == 200
    data = res.json()
    assert data["seed"] == 42
    assert data["scenario_count"] == 12
    assert "policy_summaries" in data
    assert "NO_RECOVERY" in data["policy_summaries"]
    assert "FIXED_RETRY" in data["policy_summaries"]
    assert "MANDATESHIELD" in data["policy_summaries"]
    assert "lift_metrics" in data
