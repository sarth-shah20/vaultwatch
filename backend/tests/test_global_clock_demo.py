"""Global synthetic-clock regression checks for generated CERT/PaySim demo pairs."""
from __future__ import annotations

import json
from pathlib import Path

from backend.app.shared.assessment_schema import RiskAssessmentTransport
from backend.app.shared.time_mapping import paysim_step_to_event_time

ROOT = Path(__file__).resolve().parents[2]


def test_paysim_global_clock_anchor_is_fixed() -> None:
    assert paysim_step_to_event_time(0).isoformat() == "2010-01-01T00:00:00+00:00"
    assert paysim_step_to_event_time(13).isoformat() == "2010-01-01T13:00:00+00:00"


def test_generated_demo_pairs_have_populated_labeled_times_within_window() -> None:
    cert_payload = json.loads((ROOT / "data/synthetic/cert_demo_assessments.json").read_text())
    ps2_payload = json.loads((ROOT / "data/synthetic/ps2_demo_assessments.json").read_text())
    cert = {
        assessment.entity_id: assessment
        for assessment in map(RiskAssessmentTransport.model_validate, cert_payload["assessments"])
    }
    ps2 = {
        assessment.entity_id: assessment
        for assessment in map(RiskAssessmentTransport.model_validate, ps2_payload["assessments"])
    }
    assert len(cert) == 17
    assert cert.keys() == ps2.keys()
    for entity_id in cert:
        assert cert[entity_id].domain == "ps1_behavioral"
        assert cert[entity_id].event_time is not None
        assert cert[entity_id].time_basis == "cert_simulated_local_utc"
        assert ps2[entity_id].domain == "ps2_transaction"
        assert ps2[entity_id].event_time is not None
        assert ps2[entity_id].time_basis == "synthetic_step_mapping"
        gap_seconds = abs((cert[entity_id].event_time - ps2[entity_id].event_time).total_seconds())
        assert gap_seconds <= 120 * 60
