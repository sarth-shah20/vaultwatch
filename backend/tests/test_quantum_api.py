"""Tests for the quantum crypto-inventory API endpoint."""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.core.incident_store import IncidentStore
from backend.app.main import create_app

ROOT = Path(__file__).resolve().parents[2]


def _client() -> TestClient:
    app = create_app(store=IncidentStore(":memory:"), seed=False, root=str(ROOT))
    return TestClient(app)


def test_quantum_report_summary_and_ordering() -> None:
    report = _client().get("/quantum/report").json()
    assert report["summary"]["assets"] == 12
    assert report["summary"]["quantum_vulnerable"] == 8
    assert report["summary"]["hndl_exposed"] == 5
    top = report["migration_priority"][0]
    assert top["priority_tier"] == "CRITICAL" and top["hndl_risk"] is True
    scores = [a["priority_score"] for a in report["migration_priority"]]
    assert scores == sorted(scores, reverse=True)


def test_quantum_report_recommends_nist_pqc() -> None:
    report = _client().get("/quantum/report").json()
    recs = {a["recommended_pqc"] for a in report["migration_priority"] if a["hndl_risk"]}
    assert recs <= {"ML-KEM (Kyber)", "ML-DSA (Dilithium)"}
