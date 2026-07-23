"""HTTP and Kafka adapters share Step-6 ingestion service."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from backend.app.core.assessment_ingestion import AssessmentIngestionService
from backend.app.core.incident_store import IncidentStore
from backend.app.main import create_app
from backend.app.ps2_correlation.correlation_engine import TemporalCorrelationStore
from backend.app.ps2_correlation.correlation_engine.kafka_ingestion import KafkaAssessmentConsumer
from backend.app.shared.assessment_schema import RiskAssessmentTransport
from backend.app.shared.entities import Reason, RiskAssessment

KEY = "step6-test-key"
T0 = datetime(2031, 1, 1, tzinfo=timezone.utc)


def _assessment(domain: str, minutes: int, assessment_id: str) -> dict:
    assessment = RiskAssessment(
        assessment_id=assessment_id, entity_id="CERT:LIVE-001", domain=domain,
        score=.95 if domain == "ps2_transaction" else .9, event_time=T0 + timedelta(minutes=minutes),
        reasons=[Reason("signal", domain, .9)], source="test", model_version="test-v1",
    )
    return RiskAssessmentTransport.from_entity(assessment).model_dump(mode="json")


def _client() -> TestClient:
    app = create_app(
        store=IncidentStore(":memory:"), temporal_store=TemporalCorrelationStore(":memory:"),
        seed=False, ingestion_api_key=KEY,
    )
    return TestClient(app)


def _post(client: TestClient, assessments: list[dict], key: str = KEY):
    return client.post("/assessments", headers={"X-Ingestion-API-Key": key},
                       json={"schema_version": "1.0", "assessments": assessments})


def test_http_authentication_and_live_recorrelation() -> None:
    client = _client()
    payload = _assessment("ps1_behavioral", 0, "live-ps1")
    assert _post(client, [payload], "wrong").status_code == 401

    first = _post(client, [payload]).json()
    assert first["accepted"] == ["live-ps1"]
    second = _post(client, [_assessment("ps2_transaction", 45, "live-ps2")]).json()
    assert second["accepted"] == ["live-ps2"]
    incident_id = second["affected_incident_ids"][0]
    incident = client.get(f"/incidents/{incident_id}").json()
    assert incident["confidence"] == "high"
    assert incident["access_decision"] == "revoke"
    assert incident["contributing_domains"] == ["ps1_behavioral", "ps2_transaction"]


def test_http_reports_duplicate_and_partial_rejection() -> None:
    client = _client()
    valid = _assessment("ps1_behavioral", 0, "duplicate-me")
    assert _post(client, [valid]).json()["accepted"] == ["duplicate-me"]
    result = _post(client, [valid, {"assessment_id": "bad", "score": 4}]).json()
    assert result["duplicate"] == ["duplicate-me"]
    assert result["rejected"][0]["assessment_id"] == "bad"


class _Consumer:
    def __init__(self): self.commits = 0
    def commit(self): self.commits += 1


class _Future:
    def get(self, timeout: int): return None


class _Producer:
    def __init__(self): self.messages = []
    def send(self, topic, payload):
        self.messages.append((topic, payload)); return _Future()


class _Message:
    def __init__(self, payload): self.value = json.dumps(payload).encode()


def test_kafka_adapter_commits_after_service_and_dlqs_invalid() -> None:
    consumer, producer = _Consumer(), _Producer()
    service = AssessmentIngestionService(TemporalCorrelationStore(), IncidentStore())
    adapter = KafkaAssessmentConsumer(service, consumer=consumer, producer=producer)
    result = adapter.handle_message(_Message({"schema_version": "1.0", "assessments": [_assessment("ps1_behavioral", 0, "kafka-1")]}))
    assert result["accepted"] == ["kafka-1"] and consumer.commits == 1
    adapter.handle_message(_Message({"schema_version": "bad", "assessments": []}))
    assert consumer.commits == 2
    assert producer.messages[0][0] == "vaultwatch.risk-assessments.v1.dlq"


def test_duplicate_across_http_then_kafka_does_not_double_correlate() -> None:
    client = _client()
    payload = _assessment("ps1_behavioral", 0, "cross-transport-id")
    assert _post(client, [payload]).json()["accepted"] == ["cross-transport-id"]
    app = client.app
    consumer, producer = _Consumer(), _Producer()
    adapter = KafkaAssessmentConsumer(app.state.ingestion_service, consumer=consumer, producer=producer)
    result = adapter.handle_message(_Message({"schema_version": "1.0", "assessments": [payload]}))
    assert result["duplicate"] == ["cross-transport-id"]
    assert consumer.commits == 1
    assert app.state.temporal_store.conn.execute(
        "SELECT count(*) FROM risk_assessments WHERE assessment_id=?", ("cross-transport-id",)
    ).fetchone()[0] == 1
    assert len(app.state.temporal_store.incidents_for_entity("CERT:LIVE-001")) == 1


def test_kafka_invalid_assessment_is_dlqd_with_validation_details() -> None:
    consumer, producer = _Consumer(), _Producer()
    service = AssessmentIngestionService(TemporalCorrelationStore(), IncidentStore())
    adapter = KafkaAssessmentConsumer(service, consumer=consumer, producer=producer)
    result = adapter.handle_message(_Message({
        "schema_version": "1.0",
        "assessments": [{"assessment_id": "invalid-score", "entity_id": "CERT:BAD", "domain": "ps1_behavioral", "score": 4, "reasons": []}],
    }))
    assert result["rejected"][0]["assessment_id"] == "invalid-score"
    assert consumer.commits == 1
    topic, message = producer.messages[0]
    assert topic == "vaultwatch.risk-assessments.v1.dlq"
    assert message["details"]["rejected"][0]["assessment_id"] == "invalid-score"
    assert "within [0, 1]" in message["details"]["rejected"][0]["errors"][0]["msg"]
