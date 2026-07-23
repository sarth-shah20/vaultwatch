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


def _incident_id(client: TestClient, entity_id: str) -> str:
    items = client.get("/incidents").json()["incidents"]
    return next(item["incident_id"] for item in items if item["entity_id"] == entity_id)


def test_health_and_seeded_incidents() -> None:
    client = _client()
    health = client.get("/health").json()
    assert health["status"] == "ok"
    assert health["incidents"] == 19  # 17 global CERT/PaySim pairs + 2 constructed singles

    listing = client.get("/incidents").json()
    assert listing["count"] == 19
    by_entity = {item["entity_id"]: item for item in listing["incidents"]}
    assert "CERT:CET3786" in by_entity
    # UUID-backed incident IDs are allocated by persisted correlation engine.
    assert by_entity["E010"]["access_decision"] == "step_up_auth"
    assert by_entity["E015"]["access_decision"] == "throttle"


def test_incident_detail_has_both_domains() -> None:
    client = _client()
    inc = client.get(f"/incidents/{_incident_id(client, 'CERT:CET3786')}").json()
    assert inc["entity_id"] == "CERT:CET3786"
    assert sorted(inc["contributing_domains"]) == ["ps1_behavioral", "ps2_transaction"]
    assert client.get("/incidents/NOPE").status_code == 404


def test_dismiss_feedback_flow() -> None:
    client = _client()
    incident_id = _incident_id(client, "CERT:CET3786")
    resp = client.post(f"/incidents/{incident_id}/feedback", json={"action": "dismiss", "reason": "confirmed benign"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "dismissed" and body["suppressed"] is True
    assert "CERT:CET3786" in client.get("/suppressions").json()["suppressed_entities"]

    # dismissing again -> invalid transition (409)
    again = client.post(f"/incidents/{incident_id}/feedback", json={"action": "dismiss"})
    assert again.status_code == 409


def test_bad_action_is_422() -> None:
    client = _client()
    assert client.post("/incidents/NOPE/feedback", json={"action": "nope"}).status_code == 422
