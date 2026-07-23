"""Tests for the VaultWatch Correlation API (FastAPI)."""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.core.incident_store import IncidentStore
from backend.app.main import create_app

ROOT = Path(__file__).resolve().parents[2]


def _client() -> TestClient:
    app = create_app(store=IncidentStore(":memory:"), seed=True, root=str(ROOT))
    return TestClient(app)


def test_health_and_seeded_incidents() -> None:
    client = _client()
    health = client.get("/health").json()
    assert health["status"] == "ok"
    assert health["incidents"] == 19  # 17 global CERT/PaySim pairs + 2 constructed singles

    listing = client.get("/incidents").json()
    assert listing["count"] == 19
    ids = {i["incident_id"] for i in listing["incidents"]}
    assert "INC-CERT:CET3786" in ids
    # constructed single-domain incidents still fill out the decision spectrum.
    decisions = {i["incident_id"]: i["access_decision"] for i in listing["incidents"]}
    assert decisions["INC-E010"] == "step_up_auth"
    assert decisions["INC-E015"] == "throttle"


def test_incident_detail_has_both_domains() -> None:
    client = _client()
    inc = client.get("/incidents/INC-CERT:CET3786").json()
    assert inc["entity_id"] == "CERT:CET3786"
    assert sorted(inc["contributing_domains"]) == ["ps1_behavioral", "ps2_transaction"]
    assert client.get("/incidents/NOPE").status_code == 404


def test_dismiss_feedback_flow() -> None:
    client = _client()
    resp = client.post("/incidents/INC-CERT:CET3786/feedback", json={"action": "dismiss", "reason": "confirmed benign"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "dismissed" and body["suppressed"] is True
    assert "CERT:CET3786" in client.get("/suppressions").json()["suppressed_entities"]

    # dismissing again -> invalid transition (409)
    again = client.post("/incidents/INC-CERT:CET3786/feedback", json={"action": "dismiss"})
    assert again.status_code == 409


def test_bad_action_is_422() -> None:
    client = _client()
    assert client.post("/incidents/INC-CERT:CET3786/feedback", json={"action": "nope"}).status_code == 422
