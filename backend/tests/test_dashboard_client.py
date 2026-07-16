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
    assert len(incidents) == 5  # 3 real REVOKE + 2 constructed (step-up / throttle)
    detail = client.get_incident("INC-E028")
    assert detail["entity_id"] == "E028"


def test_summarize_counts_decisions() -> None:
    client = _client()
    summary = summarize(client.list_incidents())
    assert summary["total"] == 5
    assert summary["revoke"] >= 1
    assert summary["by_confidence"].get("high", 0) == 3   # only the 3 corroborated incidents
    assert summary["by_confidence"].get("low", 0) == 2    # the 2 constructed single-domain ones


def test_reasons_grouped_by_domain() -> None:
    client = _client()
    grouped = reasons_by_domain(client.get_incident("INC-E027"))
    assert {"ps1_behavioral", "ps2_transaction"} <= set(grouped)


def test_feedback_drives_lifecycle_and_suppression() -> None:
    client = _client()
    resp = client.send_feedback("INC-E028", "dismiss", "confirmed benign")
    assert resp.status_code == 200 and resp.json()["status"] == "dismissed"
    assert "E028" in client.suppressions()
    # illegal repeat transition surfaces as a non-200 the UI can show
    assert client.send_feedback("INC-E028", "dismiss").status_code == 409
