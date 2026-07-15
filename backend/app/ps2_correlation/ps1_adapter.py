"""PS1 adapter — teammate's anomaly_results.json -> shared RiskAssessment.

The teammate's PS1 pipeline (drain3 + Isolation Forest over the DTAA security-log
dataset) emits its own `anomaly_results.json`. This adapter converts that into our
shared `RiskAssessment` (domain='ps1_behavioral') so the correlation engine can
join PS1 behavioral risk with PS2 transactional risk on a common `entity_id`.

Bridging: their logs use DTAA usernames; we resolve each to our `entity_id` via
the `ps1` crosswalk in entity_mapping.json (a deliberate, labeled demo link).

Scoring: their per-log `score` is an Isolation-Forest `decision_function` value
(more negative = more anomalous). We map it monotonically to a 0-1 risk. This is
a demo calibration, documented as such — it does not change their model.

Swap-in: when the teammate's pipeline is live, point `anomalies_path` at the file
it writes; nothing else changes.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

from backend.app.shared.entities import Reason, RiskAssessment

DOMAIN = "ps1_behavioral"
DEFAULT_ANOMALIES_PATH = "data/synthetic/ps1_anomaly_results.json"
MAPPING_PATH = "data/synthetic/entity_mapping.json"

# Calibration: decision_function ~ -0.05 -> ~0.90 risk, ~ -0.001 -> ~0.51.
SCORE_SCALE = 45.0


def normalize_score(decision_function_score: float) -> float:
    """Map an Isolation-Forest decision_function value (negative = more anomalous)
    to a 0-1 risk score (higher = riskier), monotonically."""
    return round(1.0 / (1.0 + math.exp(decision_function_score * SCORE_SCALE)), 4)


def _ps1_user_to_entity(root: Path) -> dict[str, str]:
    payload = json.loads((root / MAPPING_PATH).read_text(encoding="utf-8"))
    mapping = {}
    for record in payload["entities"]:
        ps1 = record["source_ids"].get("ps1")
        if ps1 and ps1.get("user"):
            mapping[ps1["user"]] = record["entity"]["entity_id"]
    return mapping


def load_ps1_assessments(
    root: str | Path = ".",
    anomalies_path: str = DEFAULT_ANOMALIES_PATH,
    only_mapped: bool = True,
    top_k_reasons: int = 3,
) -> list[RiskAssessment]:
    """Return one RiskAssessment per PS1-flagged entity (strongest anomaly wins)."""
    root = Path(root)
    user_to_entity = _ps1_user_to_entity(root)
    payload = json.loads((root / anomalies_path).read_text(encoding="utf-8"))

    by_entity: dict[str, list[tuple[dict, dict]]] = {}
    for anomaly in payload.get("anomalies", []):
        log = json.loads(anomaly["log"])
        entity_id = user_to_entity.get(log.get("USER"))
        if entity_id is None:
            if only_mapped:
                continue
            entity_id = f"UNMAPPED:{log.get('USER')}"
        by_entity.setdefault(entity_id, []).append((anomaly, log))

    assessments: list[RiskAssessment] = []
    for entity_id, items in by_entity.items():
        items.sort(key=lambda pair: pair[0]["score"])  # most negative (most anomalous) first
        top_anomaly, top_log = items[0]
        risk = normalize_score(top_anomaly["score"])

        reasons = [
            Reason(
                signal_name=top_log["ACTIVITY"],
                domain=DOMAIN,
                weight=risk,
                raw_value=(
                    f"PS1 Isolation Forest flagged '{top_log['ACTIVITY']}' on PC {top_log['PC']} "
                    f"at {top_log['DATE']} {top_log['HOUR']}:{top_log['MINUTE']} "
                    f"(user {top_log['USER']}); decision_function={top_anomaly['score']:.4f}"
                ),
            )
        ]
        other_activities = sorted({log["ACTIVITY"] for _, log in items} - {top_log["ACTIVITY"]})
        for activity in other_activities[: max(0, top_k_reasons - 1)]:
            reasons.append(
                Reason(
                    signal_name=activity,
                    domain=DOMAIN,
                    weight=round(risk * 0.3, 4),
                    raw_value=f"PS1 also flagged '{activity}' for user {top_log['USER']}",
                )
            )
        assessments.append(RiskAssessment(entity_id=entity_id, score=risk, reasons=reasons))

    assessments.sort(key=lambda a: a.entity_id)
    return assessments


if __name__ == "__main__":
    for a in load_ps1_assessments():
        print(f"{a.entity_id}  risk={a.score}  top={a.reasons[0].signal_name!r}")
