"""Transport-neutral assessment ingestion service.

HTTP and Kafka both submit same versioned batch envelope. This service owns
validation, idempotency outcome, SQLite temporal re-correlation, and API
incident projection; transports only authenticate/deserialize/acknowledge.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from backend.app.core.incident_store import IncidentStore
from backend.app.ps2_correlation.correlation_engine.store import TemporalCorrelationStore
from backend.app.shared.assessment_schema import SCHEMA_VERSION, RiskAssessmentTransport


class AssessmentBatchEnvelope(BaseModel):
    """Versioned envelope; assessment payloads validate individually.

    Keeping assessments as raw objects permits partial success and an explicit
    rejected list instead of rejecting an entire batch at HTTP parsing time.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = SCHEMA_VERSION
    assessments: list[dict[str, Any]] = Field(min_length=1, max_length=1000)


@dataclass
class RejectedAssessment:
    index: int
    errors: list[dict[str, Any]]
    assessment_id: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {"index": self.index, "assessment_id": self.assessment_id, "errors": self.errors}


@dataclass
class IngestionResult:
    accepted: list[str] = field(default_factory=list)
    duplicates: list[str] = field(default_factory=list)
    rejected: list[RejectedAssessment] = field(default_factory=list)
    affected_incident_ids: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "accepted": self.accepted,
            "duplicate": self.duplicates,
            "rejected": [item.as_dict() for item in self.rejected],
            "affected_incident_ids": self.affected_incident_ids,
        }


class AssessmentIngestionService:
    """Shared live-ingestion application service."""

    def __init__(self, temporal_store: TemporalCorrelationStore, incident_store: IncidentStore) -> None:
        self.temporal_store = temporal_store
        self.incident_store = incident_store

    def ingest_envelope(self, envelope: AssessmentBatchEnvelope) -> IngestionResult:
        if envelope.schema_version != SCHEMA_VERSION:
            raise ValueError(f"unsupported schema_version {envelope.schema_version!r}; expected {SCHEMA_VERSION!r}")
        result = IngestionResult()
        affected: set[str] = set()
        for index, raw in enumerate(envelope.assessments):
            try:
                assessment = RiskAssessmentTransport.model_validate(raw).to_entity()
            except ValidationError as exc:
                result.rejected.append(RejectedAssessment(
                    index=index, assessment_id=raw.get("assessment_id"), errors=exc.errors(include_url=False, include_context=False),
                ))
                continue
            inserted, incidents = self.temporal_store.ingest(assessment)
            if inserted:
                result.accepted.append(assessment.assessment_id)
            else:
                result.duplicates.append(assessment.assessment_id)
            # Projection is safe for duplicate replays too: late recovery can
            # repopulate API store without duplicating temporal assessment rows.
            self.incident_store.upsert(incidents)
            affected.update(incident.incident_id for incident in incidents)
        result.affected_incident_ids = sorted(affected)
        return result
