"""Optional Kafka adapter for ``AssessmentIngestionService``.

No broker is required for local tests. kafka-python is imported only when this
adapter is constructed without injected test doubles.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol

from backend.app.core.assessment_ingestion import AssessmentBatchEnvelope, AssessmentIngestionService

TOPIC = "vaultwatch.risk-assessments.v1"
GROUP_ID = "vaultwatch-correlation-v1"
DLQ_TOPIC = "vaultwatch.risk-assessments.v1.dlq"


@dataclass(frozen=True)
class KafkaIngestionConfig:
    bootstrap_servers: str = "localhost:9092"
    topic: str = TOPIC
    group_id: str = GROUP_ID
    dlq_topic: str = DLQ_TOPIC
    security_protocol: str = "PLAINTEXT"
    sasl_mechanism: str | None = None
    sasl_plain_username: str | None = None
    sasl_plain_password: str | None = None

    def client_kwargs(self) -> dict[str, Any]:
        values: dict[str, Any] = {"bootstrap_servers": self.bootstrap_servers, "security_protocol": self.security_protocol}
        if self.sasl_mechanism:
            values["sasl_mechanism"] = self.sasl_mechanism
        if self.sasl_plain_username:
            values["sasl_plain_username"] = self.sasl_plain_username
        if self.sasl_plain_password:
            values["sasl_plain_password"] = self.sasl_plain_password
        return values


class KafkaMessage(Protocol):
    value: bytes


class KafkaAssessmentConsumer:
    """At-least-once consumer. Commit happens only after DB handling + DLQ."""

    def __init__(self, service: AssessmentIngestionService, config: KafkaIngestionConfig = KafkaIngestionConfig(),
                 consumer: Any | None = None, producer: Any | None = None) -> None:
        self.service = service
        self.config = config
        if consumer is None or producer is None:
            try:
                from kafka import KafkaConsumer, KafkaProducer
            except ImportError as exc:  # pragma: no cover - needs optional dependency
                raise RuntimeError("Kafka adapter requires kafka-python; install backend requirements") from exc
            kwargs = config.client_kwargs()
            consumer = consumer or KafkaConsumer(config.topic, group_id=config.group_id, enable_auto_commit=False,
                                                  value_deserializer=lambda value: value, **kwargs)
            producer = producer or KafkaProducer(value_serializer=lambda value: json.dumps(value).encode("utf-8"), **kwargs)
        self.consumer = consumer
        self.producer = producer

    def handle_message(self, message: KafkaMessage) -> dict[str, Any]:
        """Persist/re-correlate, DLQ permanent invalid payloads, then commit."""
        try:
            raw = json.loads(message.value.decode("utf-8"))
            envelope = AssessmentBatchEnvelope.model_validate(raw)
            result = self.service.ingest_envelope(envelope)
            if result.rejected:
                self._send_dlq(raw, "one or more assessments failed validation", result.as_dict())
            self.consumer.commit()
            return result.as_dict()
        except (json.JSONDecodeError, ValueError) as exc:
            self._send_dlq(_best_effort_payload(message.value), str(exc), None)
            self.consumer.commit()
            return {"accepted": [], "duplicate": [], "rejected": [{"errors": [{"msg": str(exc)}]}], "affected_incident_ids": []}

    def _send_dlq(self, payload: Any, error: str, details: dict[str, Any] | None) -> None:
        future = self.producer.send(self.config.dlq_topic, {"error": error, "payload": payload, "details": details})
        if hasattr(future, "get"):
            future.get(timeout=10)


def _best_effort_payload(value: bytes) -> str:
    return value.decode("utf-8", errors="replace")
