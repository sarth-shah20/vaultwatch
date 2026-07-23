"""Tests for the dashboard API client (bound to the FastAPI app in-process)."""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.core.incident_store import IncidentStore
from backend.app.main import create_app
from dashboard.client import IncidentAPIClient, reasons_by_domain, summarize

ROOT = Path(__file__).resolve().parents[2]


def _client() -> IncidentAPIClient:
    app = create_app(store=IncidentStore(":memory:"), seed=True, root=str(ROOT))
    # starlette's TestClient is a sync httpx.Client subclass -> drop-in for the client.
    return IncidentAPIClient(http=TestClient(app))


def test_list_and_get_incidents() -> None:
    client = _client()
    incidents = client.list_incidents()
    assert len(incidents) == 19  # 17 global CERT/PaySim pairs + 2 constructed singles
    detail = client.get_incident("INC-CERT:CET3786")
    assert detail["entity_id"] == "CERT:CET3786"


def test_summarize_counts_decisions() -> None:
    client = _client()
    summary = summarize(client.list_incidents())
    assert summary["total"] == 19
    assert summary["revoke"] == 17
    assert summary["by_confidence"].get("high", 0) == 17
    assert summary["by_confidence"].get("low", 0) == 2


def test_reasons_grouped_by_domain() -> None:
    client = _client()
    grouped = reasons_by_domain(client.get_incident("INC-CERT:CET3786"))
    assert {"ps1_behavioral", "ps2_transaction"} <= set(grouped)


def test_feedback_drives_lifecycle_and_suppression() -> None:
    client = _client()
    resp = client.send_feedback("INC-CERT:CET3786", "dismiss", "confirmed benign")
    assert resp.status_code == 200 and resp.json()["status"] == "dismissed"
    assert "CERT:CET3786" in client.suppressions()
    # illegal repeat transition surfaces as a non-200 the UI can show
    assert client.send_feedback("INC-CERT:CET3786", "dismiss").status_code == 409
