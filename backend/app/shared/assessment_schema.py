"""Versioned transport schema for cross-domain risk assessments."""
from __future__ import annotations

import math
from datetime import datetime
from uuid import NAMESPACE_URL, uuid4, uuid5

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from backend.app.shared.entities import Reason, RiskAssessment

SCHEMA_VERSION = "1.0"


class ReasonTransport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    signal_name: str = Field(min_length=1)
    domain: str = Field(min_length=1)
    weight: float
    raw_value: str | None = None

    @field_validator("weight")
    @classmethod
    def finite_weight(cls, value: float) -> float:
        if not math.isfinite(value) or not 0.0 <= value <= 1.0:
            raise ValueError("reason weight must be finite and within [0, 1]")
        return value


class RiskAssessmentTransport(BaseModel):
    """JSON contract. Defaults permit loading legacy snapshots without new fields."""

    model_config = ConfigDict(extra="forbid")

    assessment_id: str = Field(default_factory=lambda: str(uuid4()), min_length=1)
    schema_version: str = SCHEMA_VERSION
    entity_id: str = Field(min_length=1)
    domain: str = "unknown"
    score: float
    reasons: list[ReasonTransport] = Field(default_factory=list)
    event_time: datetime | None = None
    window_start: datetime | None = None
    window_end: datetime | None = None
    source: str = "unknown"
    model_version: str = "unknown"
    generated_at: datetime = Field(default_factory=datetime.utcnow)

    @field_validator("score")
    @classmethod
    def finite_score(cls, value: float) -> float:
        if not math.isfinite(value) or not 0.0 <= value <= 1.0:
            raise ValueError("score must be finite and within [0, 1]")
        return value

    @model_validator(mode="after")
    def reason_domains_match(self):
        if self.domain == "unknown" and self.reasons:
            self.domain = _infer_domain_from_reasons(self.reasons)
        mismatched = [r.domain for r in self.reasons if r.domain != self.domain]
        if mismatched:
            raise ValueError(f"reason domains {mismatched} do not match assessment domain {self.domain!r}")
        return self

    @classmethod
    def from_entity(cls, assessment: RiskAssessment) -> "RiskAssessmentTransport":
        payload = {
            "assessment_id": assessment.assessment_id,
            "schema_version": assessment.schema_version,
            "entity_id": assessment.entity_id,
            "domain": assessment.domain if assessment.domain != "unknown" else _infer_domain(assessment),
            "score": assessment.score,
            "reasons": [ReasonTransport.model_validate(r.__dict__) for r in assessment.reasons],
            "event_time": assessment.event_time,
            "window_start": assessment.window_start,
            "window_end": assessment.window_end,
            "source": assessment.source,
            "model_version": assessment.model_version,
            "generated_at": assessment.generated_at,
        }
        return cls.model_validate(payload)

    def to_entity(self) -> RiskAssessment:
        return RiskAssessment(
            entity_id=self.entity_id, score=self.score,
            reasons=[Reason(**r.model_dump()) for r in self.reasons],
            assessment_id=self.assessment_id, schema_version=self.schema_version,
            domain=self.domain, event_time=self.event_time,
            window_start=self.window_start, window_end=self.window_end,
            source=self.source, model_version=self.model_version,
            generated_at=self.generated_at,
        )


def _infer_domain(assessment: RiskAssessment) -> str:
    domains = [r.domain for r in assessment.reasons if r.domain]
    return max(set(domains), key=domains.count) if domains else "unknown"


def _infer_domain_from_reasons(reasons: list[ReasonTransport]) -> str:
    domains = [r.domain for r in reasons if r.domain]
    return max(set(domains), key=domains.count) if domains else "unknown"


def stable_assessment_id(source: str, entity_id: str, event_time: datetime | None, model_version: str) -> str:
    """Stable UUID for replay idempotency."""
    stamp = event_time.isoformat() if event_time else "none"
    return str(uuid5(NAMESPACE_URL, f"vaultwatch:{source}:{entity_id}:{stamp}:{model_version}"))
