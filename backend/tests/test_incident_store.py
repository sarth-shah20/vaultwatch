"""Tests for the SQLite incident store + feedback/suppression loop."""
from __future__ import annotations

import pytest

from backend.app.core.incident_store import IncidentStore
from backend.app.core.lifecycle import InvalidTransition
from backend.app.shared.entities import (
    AccessDecision,
    IncidentStatus,
    Reason,
    RiskAssessment,
    UnifiedIncident,
)


def _incident(iid: str, eid: str, score: float = 0.95) -> UnifiedIncident:
    return UnifiedIncident(
        incident_id=iid, entity_id=eid, combined_score=score,
        contributing_assessments=[RiskAssessment(eid, score, [Reason("s", "ps1_behavioral", score, "why")])],
        status=IncidentStatus.ESCALATED, access_decision=AccessDecision.REVOKE,
        confidence="high", contributing_domains=["ps1_behavioral", "ps2_transaction"],
    )


@pytest.fixture
def store() -> IncidentStore:
    s = IncidentStore(":memory:")
    s.seed([_incident("INC-A", "E001", 0.95), _incident("INC-B", "E002", 0.6)])
    return s


def test_seed_list_and_get(store: IncidentStore) -> None:
    items = store.list_incidents()
    assert [i["incident_id"] for i in items] == ["INC-A", "INC-B"]  # sorted by score desc
    assert store.get_incident("INC-A")["entity_id"] == "E001"
    assert store.list_incidents(min_score=0.9)[0]["incident_id"] == "INC-A"
    with pytest.raises(KeyError):
        store.get_incident("NOPE")


def test_dismiss_updates_status_and_suppresses_entity(store: IncidentStore) -> None:
    updated = store.record_feedback("INC-A", "dismiss", reason="false positive")
    assert updated["status"] == IncidentStatus.DISMISSED.value
    assert updated["suppressed"] is True
    assert "E001" in store.suppressed_entities()
    assert store.feedback_log("INC-A")[0]["action"] == "dismiss"


def test_terminal_state_blocks_further_transitions(store: IncidentStore) -> None:
    store.record_feedback("INC-A", "dismiss")
    with pytest.raises(InvalidTransition):
        store.record_feedback("INC-A", "escalate")


def test_feedback_on_missing_incident_raises(store: IncidentStore) -> None:
    with pytest.raises(KeyError):
        store.record_feedback("NOPE", "acknowledge")
