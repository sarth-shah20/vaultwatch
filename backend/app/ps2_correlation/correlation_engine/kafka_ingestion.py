"""Optional Kafka adapter for ``AssessmentIngestionService``.

No broker is required for local tests. kafka-python is imported only when this
adapter is constructed without injected test doubles.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Any, Protocol

from backend.app.core.assessment_ingestion import AssessmentBatchEnvelope, AssessmentIngestionService

TOPIC = "vaultwatch.risk-assessments.v1"
GROUP_ID = "vaultwatch-correlation-v1"
DLQ_TOPIC = "vaultwatch.risk-assessments.v1.dlq"
LOGGER = logging.getLogger(__name__)


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

    @classmethod
    def from_env(cls) -> "KafkaIngestionConfig":
        """Resolve deployment settings explicitly; local default stays plaintext."""
        return cls(
            bootstrap_servers=os.getenv("VAULTWATCH_KAFKA_BOOTSTRAP_SERVERS", "localhost:9092"),
            topic=os.getenv("VAULTWATCH_KAFKA_TOPIC", TOPIC),
            group_id=os.getenv("VAULTWATCH_KAFKA_GROUP_ID", GROUP_ID),
            dlq_topic=os.getenv("VAULTWATCH_KAFKA_DLQ_TOPIC", DLQ_TOPIC),
            security_protocol=os.getenv("VAULTWATCH_KAFKA_SECURITY_PROTOCOL", "PLAINTEXT"),
            sasl_mechanism=os.getenv("VAULTWATCH_KAFKA_SASL_MECHANISM") or None,
            sasl_plain_username=os.getenv("VAULTWATCH_KAFKA_SASL_USERNAME") or None,
            sasl_plain_password=os.getenv("VAULTWATCH_KAFKA_SASL_PASSWORD") or None,
        )

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
    """At-least-once consumer. Commit happens only after DB handling + DLQ.

    Caller must poll until ``consumer.assignment()`` is non-empty before
    publishing test records; publishing earlier with ``latest`` offset policy
    can race group assignment and make records appear missing.
    """

    def __init__(self, service: AssessmentIngestionService, config: KafkaIngestionConfig | None = None,
                 consumer: Any | None = None, producer: Any | None = None) -> None:
        self.service = service
        self.config = config or KafkaIngestionConfig.from_env()
        LOGGER.info(
            "Kafka assessment consumer config bootstrap_servers=%s topic=%s group_id=%s security_protocol=%s",
            self.config.bootstrap_servers, self.config.topic, self.config.group_id, self.config.security_protocol,
        )
        if consumer is None or producer is None:
            try:
                from kafka import KafkaConsumer, KafkaProducer
            except ImportError as exc:  # pragma: no cover - needs optional dependency
                raise RuntimeError("Kafka adapter requires kafka-python; install backend requirements") from exc
            kwargs = self.config.client_kwargs()
            consumer = consumer or KafkaConsumer(self.config.topic, group_id=self.config.group_id, enable_auto_commit=False,
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
