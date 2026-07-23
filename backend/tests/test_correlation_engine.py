"""Temporal-correlation and persisted-ingestion tests."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from backend.app.ps2_correlation.correlation_engine import (
    CorrelationConfig, TemporalCorrelationStore, build_demo_incidents,
    correlate, decide_access, fuse_scores,
)
from backend.app.shared.assessment_schema import RiskAssessmentTransport
from backend.app.shared.entities import AccessDecision, IncidentStatus, Reason, RiskAssessment

ROOT = Path(__file__).resolve().parents[2]
T0 = datetime(2010, 1, 1, tzinfo=timezone.utc)


def _ra(entity_id: str, score: float, domain: str, minutes: int | None, assessment_id: str | None = None) -> RiskAssessment:
    return RiskAssessment(
        entity_id=entity_id, score=score,
        reasons=[Reason(signal_name="s", domain=domain, weight=score, raw_value="x")],
        domain=domain, assessment_id=assessment_id or f"{entity_id}-{domain}-{minutes}",
        event_time=T0 + timedelta(minutes=minutes) if minutes is not None else None,
    )


def test_fuse_boosts_corroboration_level() -> None:
    lone, n_lone, level_lone = fuse_scores({"ps2_transaction": 0.9})
    corr, n_corr, level_corr = fuse_scores({"ps1_behavioral": 0.8, "ps2_transaction": 0.7})
    assert (level_lone, n_lone, lone) == ("low", 1, 0.9)
    assert (level_corr, n_corr) == ("high", 2)
    assert corr > (0.8 + 0.7) / 2


def test_decision_requires_corroboration_to_revoke() -> None:
    assert decide_access(0.95, "low") == AccessDecision.STEP_UP_AUTH
    assert decide_access(0.95, "high") == AccessDecision.REVOKE


def test_inside_window_different_domains_correlate() -> None:
    incidents = correlate([_ra("X1", .95, "ps2_transaction", 0), _ra("X1", .8, "ps1_behavioral", 119)])
    assert len(incidents) == 1
    assert incidents[0].confidence == "high"  # corroboration level, not statistical confidence
    assert incidents[0].status == IncidentStatus.ESCALATED
    assert incidents[0].access_decision == AccessDecision.REVOKE


def test_outside_window_creates_separate_incidents() -> None:
    incidents = correlate([_ra("X1", .95, "ps2_transaction", 0), _ra("X1", .8, "ps1_behavioral", 121)])
    assert len(incidents) == 2
    assert all(incident.confidence == "low" for incident in incidents)


def test_same_domain_updates_strongest_but_never_corroborates() -> None:
    store = TemporalCorrelationStore()
    store.ingest(_ra("X1", .7, "ps1_behavioral", 0, "first"))
    _, incidents = store.ingest(_ra("X1", .95, "ps1_behavioral", 10, "stronger"))
    assert len(incidents) == 1
    assert incidents[0].confidence == "low"
    assert incidents[0].contributing_domains == ["ps1_behavioral"]
    assert [item.assessment_id for item in incidents[0].contributing_assessments] == ["stronger"]


def test_idempotency_and_out_of_order_recorrelation() -> None:
    store = TemporalCorrelationStore()
    ps2 = _ra("X1", .95, "ps2_transaction", 110, "ps2")
    inserted, before = store.ingest(ps2)
    assert inserted and before[0].confidence == "low"
    original_id = before[0].incident_id
    inserted, after = store.ingest(_ra("X1", .8, "ps1_behavioral", 0, "ps1"))
    assert inserted and len(after) == 1
    assert after[0].incident_id == original_id
    assert after[0].confidence == "high"
    duplicate, replay = store.ingest(ps2)
    assert not duplicate and replay[0].incident_id == original_id


def test_configurable_window_and_untimed_assessments() -> None:
    store = TemporalCorrelationStore(config=CorrelationConfig(window_minutes=10))
    store.ingest_many([_ra("X1", .9, "ps2_transaction", 0), _ra("X1", .8, "ps1_behavioral", 11)])
    assert len(store.incidents_for_entity("X1")) == 2
    untimed = correlate([_ra("Y1", .9, "ps2_transaction", None), _ra("Y1", .8, "ps1_behavioral", None)])
    assert len(untimed) == 2
    assert all(incident.confidence == "low" for incident in untimed)


def test_real_engine_correlates_cet3786_demo_pair() -> None:
    def load(path: str) -> dict[str, RiskAssessment]:
        payload = json.loads((ROOT / path).read_text())
        items = [RiskAssessmentTransport.model_validate(item).to_entity() for item in payload["assessments"]]
        return {item.entity_id: item for item in items}

    cert = load("data/synthetic/cert_demo_assessments.json")["CERT:CET3786"]
    paysim = load("data/synthetic/ps2_demo_assessments.json")["CERT:CET3786"]
    store = TemporalCorrelationStore()
    store.ingest(cert)
    _, incidents = store.ingest(paysim)
    assert len(incidents) == 1
    incident = incidents[0]
    assert incident.confidence == "high"
    assert incident.access_decision == AccessDecision.REVOKE
    assert {item.domain for item in incident.contributing_assessments} == {"ps1_behavioral", "ps2_transaction"}


def test_build_demo_incidents_runs_persisted_engine() -> None:
    incidents = build_demo_incidents(root=str(ROOT))
    cert_incidents = [item for item in incidents if item.entity_id.startswith("CERT:")]
    assert len(cert_incidents) == 17
    assert all(item.confidence == "high" and item.status == IncidentStatus.ESCALATED for item in cert_incidents)
