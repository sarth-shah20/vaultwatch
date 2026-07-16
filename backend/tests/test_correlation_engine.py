"""Tests for the Step 6 correlation engine."""
from __future__ import annotations

from pathlib import Path

from backend.app.ps2_correlation.correlation_engine import (
    build_demo_incidents,
    correlate,
    decide_access,
    fuse_scores,
)
from backend.app.shared.entities import AccessDecision, IncidentStatus, Reason, RiskAssessment

ROOT = Path(__file__).resolve().parents[2]


def _ra(entity_id, score, domain):
    return RiskAssessment(entity_id=entity_id, score=score,
                          reasons=[Reason(signal_name="s", domain=domain, weight=score, raw_value="x")])


def test_fuse_boosts_corroboration_and_flags_confidence() -> None:
    lone, n_lone, conf_lone = fuse_scores({"ps2_transaction": 0.9})
    corr, n_corr, conf_corr = fuse_scores({"ps1_behavioral": 0.8, "ps2_transaction": 0.7})
    assert conf_lone == "low" and n_lone == 1 and lone == 0.9
    assert conf_corr == "high" and n_corr == 2
    assert corr > (0.8 + 0.7) / 2  # boosted above the plain average


def test_decision_requires_corroboration_to_revoke() -> None:
    # lone strong signal -> step up (not revoke); corroborated strong -> revoke
    assert decide_access(0.95, "low") == AccessDecision.STEP_UP_AUTH
    assert decide_access(0.95, "high") == AccessDecision.REVOKE
    assert decide_access(0.5, "high") == AccessDecision.THROTTLE
    assert decide_access(0.2, "high") == AccessDecision.ALLOW


def test_lone_signal_steps_up_corroborated_revokes() -> None:
    ps2 = _ra("X1", 0.95, "ps2_transaction")
    ps1 = _ra("X1", 0.80, "ps1_behavioral")

    lone = correlate([ps2])[0]
    assert lone.confidence == "low"
    assert lone.status == IncidentStatus.NEW
    assert lone.access_decision == AccessDecision.STEP_UP_AUTH

    corr = correlate([ps2, ps1])[0]
    assert corr.confidence == "high"
    assert corr.status == IncidentStatus.ESCALATED
    assert corr.access_decision == AccessDecision.REVOKE
    assert sorted(corr.contributing_domains) == ["ps1_behavioral", "ps2_transaction"]
    assert len(corr.contributing_assessments) == 2


def test_correlate_groups_by_entity() -> None:
    incidents = correlate([_ra("A", 0.9, "ps2_transaction"), _ra("B", 0.6, "ps1_behavioral")])
    assert {i.entity_id for i in incidents} == {"A", "B"}
    # sorted by combined_score desc
    assert incidents[0].combined_score >= incidents[1].combined_score


def test_build_demo_incidents_are_corroborated_and_differentiated() -> None:
    incidents = build_demo_incidents(root=str(ROOT))
    by_entity = {i.entity_id: i for i in incidents}
    for eid in ("E027", "E028", "E029"):
        inc = by_entity[eid]
        assert inc.confidence == "high"
        assert inc.status == IncidentStatus.ESCALATED
        assert inc.access_decision == AccessDecision.REVOKE
        assert sorted(inc.contributing_domains) == ["ps1_behavioral", "ps2_transaction"]
    # scores are graduated, not all identical (no saturation)
    scores = {round(by_entity[e].combined_score, 4) for e in ("E027", "E028", "E029")}
    assert len(scores) == 3
