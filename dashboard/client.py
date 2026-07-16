"""Thin, testable client for the VaultWatch Correlation API.

The Streamlit dashboard uses this to talk to the FastAPI backend; keeping the
HTTP/data-shaping logic here (and the UI thin) makes it unit-testable. An httpx
client can be injected for tests (bound to the ASGI app), otherwise it targets
the configured base URL.
"""
from __future__ import annotations

import os
from typing import Any, Optional

import httpx

DEFAULT_BASE_URL = os.environ.get("VAULTWATCH_API", "http://localhost:8000")

# Color per access decision, for the dashboard.
DECISION_COLOR = {
    "revoke": "#c0392b",
    "step_up_auth": "#e67e22",
    "throttle": "#f1c40f",
    "allow": "#27ae60",
}


class IncidentAPIClient:
    def __init__(self, base_url: str = DEFAULT_BASE_URL, http: Optional[httpx.Client] = None) -> None:
        self._http = http or httpx.Client(base_url=base_url, timeout=10.0)

    def health(self) -> dict:
        return self._http.get("/health").json()

    def list_incidents(self, status: Optional[str] = None, min_score: Optional[float] = None) -> list[dict]:
        params = {k: v for k, v in {"status": status, "min_score": min_score}.items() if v is not None}
        resp = self._http.get("/incidents", params=params)
        resp.raise_for_status()
        return resp.json()["incidents"]

    def get_incident(self, incident_id: str) -> dict:
        resp = self._http.get(f"/incidents/{incident_id}")
        resp.raise_for_status()
        return resp.json()

    def send_feedback(self, incident_id: str, action: str, reason: Optional[str] = None) -> httpx.Response:
        return self._http.post(f"/incidents/{incident_id}/feedback", json={"action": action, "reason": reason})

    def suppressions(self) -> list[str]:
        return self._http.get("/suppressions").json()["suppressed_entities"]


def summarize(incidents: list[dict]) -> dict[str, Any]:
    """Aggregate for the dashboard header (counts by decision / confidence)."""
    by_decision: dict[str, int] = {}
    by_confidence: dict[str, int] = {}
    for inc in incidents:
        by_decision[inc.get("access_decision") or "none"] = by_decision.get(inc.get("access_decision") or "none", 0) + 1
        by_confidence[inc.get("confidence") or "n/a"] = by_confidence.get(inc.get("confidence") or "n/a", 0) + 1
    return {
        "total": len(incidents),
        "by_decision": by_decision,
        "by_confidence": by_confidence,
        "revoke": by_decision.get("revoke", 0),
        "suppressed": sum(1 for i in incidents if i.get("suppressed")),
    }


def reasons_by_domain(incident: dict) -> dict[str, list[dict]]:
    """Group an incident's contributing reasons by domain (ps1_behavioral / ps2_transaction)."""
    grouped: dict[str, list[dict]] = {}
    for assessment in incident.get("contributing_assessments", []):
        for reason in assessment.get("reasons", []):
            grouped.setdefault(reason.get("domain", "unknown"), []).append(reason)
    return grouped
