from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from backend.app.shared.assessment_schema import RiskAssessmentTransport, stable_assessment_id
from backend.app.shared.entities import Reason, RiskAssessment


def test_transport_round_trip_and_legacy_defaults() -> None:
    legacy = {
        "entity_id": "E027", "score": 0.8,
        "reasons": [{"signal_name": "off_hours", "domain": "ps1_behavioral", "weight": 0.8, "raw_value": "02:00"}],
    }
    model = RiskAssessmentTransport.model_validate(legacy)
    assert model.domain == "ps1_behavioral"
    assert model.schema_version == "1.0"
    assert model.source == "unknown"
    assert model.to_entity().entity_id == "E027"


def test_contract_rejects_invalid_score_and_reason_domain() -> None:
    with pytest.raises(ValidationError):
        RiskAssessmentTransport(entity_id="E1", domain="ps1_behavioral", score=1.1)
    with pytest.raises(ValidationError):
        RiskAssessmentTransport(
            entity_id="E1", domain="ps1_behavioral", score=0.4,
            reasons=[{"signal_name": "x", "domain": "ps2_transaction", "weight": 0.4}],
        )


def test_stable_id_and_event_fields() -> None:
    event_time = datetime(2026, 7, 23, 12, tzinfo=timezone.utc)
    a = RiskAssessment(
        entity_id="E1", score=0.4, reasons=[Reason("x", "ps1_behavioral", 0.4)],
        domain="ps1_behavioral", event_time=event_time, source="cert", model_version="cert-v1",
        assessment_id=stable_assessment_id("cert", "E1", event_time, "cert-v1"),
    )
    b = RiskAssessmentTransport.from_entity(a)
    assert b.event_time == event_time
    assert b.assessment_id == a.assessment_id
    assert b.assessment_id == stable_assessment_id("cert", "E1", event_time, "cert-v1")
