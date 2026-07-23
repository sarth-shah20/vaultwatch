"""Step 6 — correlation engine.

Fuses per-domain ``RiskAssessment`` objects (PS1 behavioral + PS2 transactional,
and any future domain) into ``UnifiedIncident`` cases, grouped by ``entity_id``.

Design (the "correlation reduces false positives" thesis, made concrete):
- A lone signal keeps its own score but is marked ``confidence="low"`` — it is NOT
  auto-escalated to a revoke; it gets step-up verification instead.
- When two or more independent domains corroborate for the same entity, the score
  is boosted toward 1 (graduated, not saturated) and marked ``confidence="high"``,
  which is what unlocks a revoke.

So two weak-ish signals that agree outrank a single strong-ish signal — exactly
the noise-filtering argument.
"""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping

from backend.app.shared.assessment_schema import RiskAssessmentTransport
from backend.app.shared.entities import (
    AccessDecision,
    IncidentStatus,
    RiskAssessment,
    UnifiedIncident,
)

FIRE_THRESHOLD = 0.5      # a domain "fires" at or above this score
AGREEMENT_BONUS = 0.3     # lift toward 1 per extra corroborating domain


def assessment_domain(assessment: RiskAssessment) -> str:
    """Infer an assessment's domain from its reasons (they are homogeneous)."""
    if assessment.domain and assessment.domain != "unknown":
        return assessment.domain
    domains = [r.domain for r in assessment.reasons if r.domain]
    if not domains:
        return "unknown"
    return max(set(domains), key=domains.count)


def fuse_scores(domain_scores: Mapping[str, float], weights: Mapping[str, float] | None = None):
    """Return (combined_score, n_domains_firing, confidence)."""
    if not domain_scores:
        return 0.0, 0, "low"
    weights = weights or {}
    wsum = sum(weights.get(d, 1.0) for d in domain_scores) or 1.0
    wavg = sum(weights.get(d, 1.0) * s for d, s in domain_scores.items()) / wsum
    n_fire = sum(1 for s in domain_scores.values() if s >= FIRE_THRESHOLD)

    if n_fire >= 2:
        combined = wavg + (1.0 - wavg) * AGREEMENT_BONUS * (n_fire - 1)
        confidence = "high"
    else:
        combined = wavg  # lone (or no) signal: keep its own weight, low confidence
        confidence = "low"
    return round(min(1.0, combined), 4), n_fire, confidence


def decide_access(combined_score: float, confidence: str) -> AccessDecision:
    """Map score + confidence to an access decision. A revoke requires BOTH a high
    score AND corroboration (high confidence) — a lone strong signal only steps up."""
    if combined_score >= 0.9 and confidence == "high":
        return AccessDecision.REVOKE
    if combined_score >= 0.7:
        return AccessDecision.STEP_UP_AUTH
    if combined_score >= 0.4:
        return AccessDecision.THROTTLE
    return AccessDecision.ALLOW


def correlate(
    assessments: Iterable[RiskAssessment],
    weights: Mapping[str, float] | None = None,
    incident_prefix: str = "INC",
) -> list[UnifiedIncident]:
    """Group assessments by entity_id and fuse them into UnifiedIncidents."""
    by_entity: dict[str, list[RiskAssessment]] = defaultdict(list)
    for a in assessments:
        by_entity[a.entity_id].append(a)

    incidents: list[UnifiedIncident] = []
    for entity_id, items in by_entity.items():
        # strongest score per domain
        domain_scores: dict[str, float] = {}
        for a in items:
            d = assessment_domain(a)
            domain_scores[d] = max(domain_scores.get(d, 0.0), float(a.score))

        combined, n_fire, confidence = fuse_scores(domain_scores, weights)
        incidents.append(
            UnifiedIncident(
                incident_id=f"{incident_prefix}-{entity_id}",
                entity_id=entity_id,
                combined_score=combined,
                contributing_assessments=list(items),
                status=IncidentStatus.ESCALATED if n_fire >= 2 else IncidentStatus.NEW,
                access_decision=decide_access(combined, confidence),
                confidence=confidence,
                contributing_domains=sorted(domain_scores),
            )
        )

    incidents.sort(key=lambda inc: inc.combined_score, reverse=True)
    return incidents


# --- Demo wiring (self-contained: reads committed PS1 + PS2 assessment artifacts) ---

def build_demo_incidents(root: str = ".") -> list[UnifiedIncident]:
    """Correlate the committed demo PS1 + PS2 assessments into UnifiedIncidents."""
    import json
    from pathlib import Path

    from backend.app.ps2_correlation.ps1_adapter import load_ps1_assessments

    root = Path(root)

    def _load_assessments(rel_path: str) -> list[RiskAssessment]:
        path = root / rel_path
        if not path.exists():
            return []
        payload = json.loads(path.read_text(encoding="utf-8"))
        fields = set(RiskAssessmentTransport.model_fields)
        return [
            RiskAssessmentTransport.model_validate({k: v for k, v in a.items() if k in fields}).to_entity()
            for a in payload["assessments"]
        ]

    cert_demo = _load_assessments("data/synthetic/cert_demo_assessments.json")
    # Prefer globally timed CERT model outputs when present; keep legacy DTAA
    # adapter as compatibility fallback for repositories without migration artifacts.
    ps1 = cert_demo or load_ps1_assessments(root=root)
    ps2 = _load_assessments("data/synthetic/ps2_demo_assessments.json")
    # Clearly-labeled CONSTRUCTED single-domain assessments (optional file) so the
    # dashboard shows the full decision spectrum (step-up / throttle) next to the
    # real corroborated REVOKE incidents.
    constructed = _load_assessments("data/synthetic/constructed_incidents.json")
    return correlate([*ps1, *ps2, *constructed])


if __name__ == "__main__":
    for inc in build_demo_incidents("."):
        print(f"{inc.incident_id}  score={inc.combined_score}  confidence={inc.confidence}  "
              f"domains={inc.contributing_domains}  status={inc.status.value}  "
              f"decision={inc.access_decision.value}")
