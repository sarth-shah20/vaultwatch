"""Tests for the PS1 adapter (anomaly_results.json -> RiskAssessment)."""
from __future__ import annotations

from pathlib import Path

from backend.app.ps2_correlation.ps1_adapter import (
    DOMAIN,
    load_ps1_assessments,
    normalize_score,
)
from backend.app.shared.entities import Reason, RiskAssessment

ROOT = Path(__file__).resolve().parents[2]


def test_normalize_score_is_monotonic_and_bounded() -> None:
    # more negative decision_function = more anomalous = higher risk
    assert normalize_score(-0.10) > normalize_score(-0.01) > normalize_score(0.0)
    for s in (-0.5, -0.05, 0.0, 0.2):
        assert 0.0 <= normalize_score(s) <= 1.0


def test_load_ps1_assessments_covers_demo_entities() -> None:
    assessments = {a.entity_id: a for a in load_ps1_assessments(root=ROOT)}
    for eid in ("E027", "E028", "E029"):
        assert eid in assessments, f"{eid} should have a PS1 assessment"
        a = assessments[eid]
        assert isinstance(a, RiskAssessment)
        assert 0.0 <= a.score <= 1.0
        assert a.reasons and all(isinstance(r, Reason) for r in a.reasons)
        assert all(r.domain == DOMAIN for r in a.reasons)
        # primary reason names the flagged behavioral activity
        assert isinstance(a.reasons[0].signal_name, str) and a.reasons[0].signal_name


def test_only_mapped_entities_by_default() -> None:
    # default only_mapped=True -> every assessment resolves to a real entity_id
    for a in load_ps1_assessments(root=ROOT):
        assert not a.entity_id.startswith("UNMAPPED:")
