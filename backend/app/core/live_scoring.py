"""Live in-process scoring for the raw-ish ingestion endpoints.

Moves the live boundary from *scored assessments* to *unscored inputs*: the
server runs the existing models in-process, produces a validated
``RiskAssessment``, and feeds the same ``AssessmentIngestionService`` used by
``POST /assessments`` (so temporal correlation and incident upsert are reused
unchanged).

Honesty boundary: model INFERENCE is live here. Raw log -> feature engineering
(CERT 30-day baselines, PaySim trailing-window features) remains an offline batch
stage. Inputs are prepared feature rows/windows, not raw logs.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from backend.app.core.assessment_ingestion import AssessmentBatchEnvelope, AssessmentIngestionService
from backend.app.shared.assessment_schema import RiskAssessmentTransport
from backend.app.shared.entities import RiskAssessment
from backend.app.shared.entity_mapping import resolve_entity


class TransactionIngestRequest(BaseModel):
    """One prepared PaySim feature row to score live."""

    model_config = ConfigDict(extra="forbid")

    type: str = Field(min_length=1, description="raw transaction type; only TRANSFER/CASH_OUT are scored")
    entity_id: str | None = None
    name_orig: str | None = Field(default=None, description="PaySim origin account, resolved via the entity mapping when entity_id is absent")
    event_time: datetime | None = None
    step: int | None = None
    features: dict[str, float] = Field(default_factory=dict, description="the 18 fraud model feature columns")


class BehavioralWindowIngestRequest(BaseModel):
    """One prepared CERT behavioral window to score live."""

    model_config = ConfigDict(extra="forbid")

    user_id: str = Field(min_length=1)
    entity_id: str | None = None
    window_start: datetime | None = None
    window_end: datetime | None = None
    event_time: datetime | None = None
    features: dict[str, float] = Field(default_factory=dict, description="the CERT model feature columns")


class _TransactionScorer(Protocol):
    def score_row(self, row: Any, entity_id: str | None = ..., top_k: int = ...) -> RiskAssessment | None: ...


class _BehavioralScorer(Protocol):
    def score_window(self, window: Any, entity_id: str | None = ...) -> RiskAssessment | None: ...


def _resolve_entity(explicit: str | None, raw_id: str | None, source: str) -> str | None:
    """Prefer an explicit canonical id; else resolve via the mapping; else None."""
    if explicit:
        return explicit
    if raw_id:
        try:
            return resolve_entity(raw_id, source)
        except ValueError:
            return None
    return None


def _ingest(assessment: RiskAssessment, ingestion_service: AssessmentIngestionService) -> dict[str, Any]:
    envelope = AssessmentBatchEnvelope(
        assessments=[RiskAssessmentTransport.from_entity(assessment).model_dump(mode="json")],
    )
    result = ingestion_service.ingest_envelope(envelope)
    return {
        "score": round(assessment.score, 6),
        "assessment_id": assessment.assessment_id,
        "entity_id": assessment.entity_id,
        "domain": assessment.domain,
        **result.as_dict(),
    }


def score_and_ingest_transaction(
    scorer: _TransactionScorer, ingestion_service: AssessmentIngestionService, req: TransactionIngestRequest,
) -> dict[str, Any]:
    entity_id = _resolve_entity(req.entity_id, req.name_orig, "paysim")
    row: dict[str, Any] = dict(req.features)
    row["type"] = req.type
    if req.event_time is not None:
        row["event_time"] = req.event_time
    if req.step is not None:
        row["step"] = req.step
    assessment = scorer.score_row(row, entity_id=entity_id)
    if assessment is None:
        return {"scored": False, "reason": "transaction type is not fraud-eligible (TRANSFER/CASH_OUT)"}
    return {"scored": True, **_ingest(assessment, ingestion_service)}


def score_and_ingest_behavioral(
    scorer: _BehavioralScorer, ingestion_service: AssessmentIngestionService, req: BehavioralWindowIngestRequest,
) -> dict[str, Any]:
    entity_id = _resolve_entity(req.entity_id, req.user_id, "cert")
    window: dict[str, Any] = dict(req.features)
    window["user_id"] = req.user_id
    window["window_start"] = req.window_start
    window["window_end"] = req.window_end
    window["event_time"] = req.event_time
    assessment = scorer.score_window(window, entity_id=entity_id)
    if assessment is None:
        return {"alerted": False, "reason": "calibrated risk below alert threshold"}
    return {"alerted": True, **_ingest(assessment, ingestion_service)}
