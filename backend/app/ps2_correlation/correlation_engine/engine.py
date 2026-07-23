"""Temporal cross-domain correlation.

``high``/``low`` are corroboration levels: two independent domains firing in
one configured time window is high corroboration. They are not probabilities
or statistical confidence estimates.
"""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from uuid import uuid4

from backend.app.ps2_correlation.correlation_engine.config import (
    DEFAULT_CORRELATION_CONFIG,
    CorrelationConfig,
)
from backend.app.shared.assessment_schema import RiskAssessmentTransport
from backend.app.shared.entities import AccessDecision, IncidentStatus, RiskAssessment, UnifiedIncident


def assessment_domain(assessment: RiskAssessment) -> str:
    if assessment.domain and assessment.domain != "unknown":
        return assessment.domain
    domains = [reason.domain for reason in assessment.reasons if reason.domain]
    return max(set(domains), key=domains.count) if domains else "unknown"


def fuse_scores(
    domain_scores: Mapping[str, float], weights: Mapping[str, float] | None = None,
    config: CorrelationConfig = DEFAULT_CORRELATION_CONFIG,
):
    """Return combined score, firing-domain count, corroboration level."""
    if not domain_scores:
        return 0.0, 0, "low"
    weights = weights or {}
    weight_sum = sum(weights.get(domain, 1.0) for domain in domain_scores) or 1.0
    weighted_average = sum(weights.get(domain, 1.0) * score for domain, score in domain_scores.items()) / weight_sum
    firing = sum(score >= config.fire_threshold for score in domain_scores.values())
    if firing >= 2:
        score = weighted_average + (1.0 - weighted_average) * config.agreement_bonus * (firing - 1)
        return round(min(1.0, score), 4), firing, "high"
    return round(weighted_average, 4), firing, "low"


def decide_access(
    combined_score: float, corroboration: str, config: CorrelationConfig = DEFAULT_CORRELATION_CONFIG,
) -> AccessDecision:
    if combined_score >= config.revoke_threshold and corroboration == "high":
        return AccessDecision.REVOKE
    if combined_score >= config.step_up_threshold:
        return AccessDecision.STEP_UP_AUTH
    if combined_score >= config.throttle_threshold:
        return AccessDecision.THROTTLE
    return AccessDecision.ALLOW


def correlate_window(
    assessments: list[RiskAssessment], config: CorrelationConfig = DEFAULT_CORRELATION_CONFIG,
    incident_id: str | None = None, weights: Mapping[str, float] | None = None,
) -> UnifiedIncident:
    """Fuse one validated entity/time window.

    Only strongest assessment per domain contributes. Repeated same-domain
    evidence improves that domain's evidence, never corroboration.
    """
    if not assessments:
        raise ValueError("cannot correlate empty assessment window")
    entity_id = assessments[0].entity_id
    if any(a.entity_id != entity_id for a in assessments):
        raise ValueError("all assessments must share canonical entity_id")
    strongest: dict[str, RiskAssessment] = {}
    for assessment in assessments:
        domain = assessment_domain(assessment)
        previous = strongest.get(domain)
        newer = (assessment.event_time or assessment.generated_at) > (previous.event_time or previous.generated_at) if previous else False
        if previous is None or assessment.score > previous.score or (assessment.score == previous.score and newer):
            strongest[domain] = assessment
    domain_scores = {domain: assessment.score for domain, assessment in strongest.items()}
    combined, firing, corroboration = fuse_scores(domain_scores, weights, config)
    return UnifiedIncident(
        incident_id=incident_id or f"INC-{uuid4()}", entity_id=entity_id,
        combined_score=combined, contributing_assessments=list(strongest.values()),
        status=IncidentStatus.ESCALATED if firing >= 2 else IncidentStatus.NEW,
        access_decision=decide_access(combined, corroboration, config),
        confidence=corroboration, contributing_domains=sorted(strongest),
    )


def correlate(
    assessments: Iterable[RiskAssessment], weights: Mapping[str, float] | None = None,
    incident_prefix: str = "INC", config: CorrelationConfig = DEFAULT_CORRELATION_CONFIG,
) -> list[UnifiedIncident]:
    """Stateless temporal correlation. Persisted ingestion uses store class."""
    from backend.app.ps2_correlation.correlation_engine.store import _temporal_groups

    by_entity: dict[str, list[RiskAssessment]] = defaultdict(list)
    for assessment in assessments:
        by_entity[assessment.entity_id].append(assessment)
    incidents = [
        correlate_window(group, config=config, incident_id=f"{incident_prefix}-{uuid4()}", weights=weights)
        for items in by_entity.values() for group in _temporal_groups(items, config)
    ]
    return sorted(incidents, key=lambda incident: incident.combined_score, reverse=True)


def build_demo_incidents(root: str = ".") -> list[UnifiedIncident]:
    """Run committed assessments through persisted real correlation engine."""
    import json
    from pathlib import Path

    from backend.app.ps2_correlation.correlation_engine.store import TemporalCorrelationStore
    from backend.app.ps2_correlation.ps1_adapter import load_ps1_assessments

    root_path = Path(root)

    def load(rel_path: str) -> list[RiskAssessment]:
        path = root_path / rel_path
        if not path.exists():
            return []
        payload = json.loads(path.read_text(encoding="utf-8"))
        fields = set(RiskAssessmentTransport.model_fields)
        return [RiskAssessmentTransport.model_validate({key: value for key, value in item.items() if key in fields}).to_entity() for item in payload["assessments"]]

    cert = load("data/synthetic/cert_demo_assessments.json")
    ps1 = cert or load_ps1_assessments(root=root_path)
    ps2 = load("data/synthetic/ps2_demo_assessments.json")
    constructed = load("data/synthetic/constructed_incidents.json")
    store = TemporalCorrelationStore()
    return store.ingest_many([*ps1, *ps2, *constructed])
