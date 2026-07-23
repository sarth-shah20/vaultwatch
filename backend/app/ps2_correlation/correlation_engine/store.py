"""SQLite persistence plus out-of-order temporal re-correlation."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from backend.app.api.serialize import to_dict
from backend.app.ps2_correlation.correlation_engine.config import DEFAULT_CORRELATION_CONFIG, CorrelationConfig
from backend.app.ps2_correlation.correlation_engine.engine import correlate_window
from backend.app.shared.assessment_schema import RiskAssessmentTransport
from backend.app.shared.entities import AccessDecision, IncidentStatus, RiskAssessment, UnifiedIncident


def _utc_iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


class TemporalCorrelationStore:
    """Assessment ledger and materialized incidents.

    Each assessment is immutable/idempotent by ``assessment_id``. Every arrival
    re-windows all records for its entity, so out-of-order records converge to
    same result as ordered replay.
    """

    def __init__(self, db_path: str = ":memory:", config: CorrelationConfig = DEFAULT_CORRELATION_CONFIG) -> None:
        if db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.config = config
        self._init()

    def _init(self) -> None:
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS risk_assessments (
                assessment_id TEXT PRIMARY KEY,
                entity_id TEXT NOT NULL,
                domain TEXT NOT NULL,
                event_time TEXT,
                payload TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_risk_assessments_entity_time
                ON risk_assessments(entity_id, event_time);
            CREATE TABLE IF NOT EXISTS temporal_incidents (
                incident_id TEXT PRIMARY KEY,
                entity_id TEXT NOT NULL,
                window_start TEXT,
                window_end TEXT,
                assessment_ids TEXT NOT NULL,
                payload TEXT NOT NULL,
                open INTEGER NOT NULL DEFAULT 1
            );
            CREATE INDEX IF NOT EXISTS idx_temporal_incidents_entity
                ON temporal_incidents(entity_id, open);
        """)
        self.conn.commit()

    def ingest(self, assessment: RiskAssessment) -> tuple[bool, list[UnifiedIncident]]:
        """Persist one assessment. Duplicate ID is no-op replay.

        Untimed assessments persist but cannot cross-correlate; each makes a
        separate low-corroboration incident.
        """
        payload = RiskAssessmentTransport.from_entity(assessment).model_dump(mode="json")
        cursor = self.conn.execute(
            "INSERT OR IGNORE INTO risk_assessments (assessment_id, entity_id, domain, event_time, payload) VALUES (?,?,?,?,?)",
            (assessment.assessment_id, assessment.entity_id, assessment.domain,
             _utc_iso(assessment.event_time) if assessment.event_time else None,
             json.dumps(payload, sort_keys=True)),
        )
        if cursor.rowcount == 0:
            self.conn.commit()
            return False, self.incidents_for_entity(assessment.entity_id)
        incidents = self._recorrelate_entity(assessment.entity_id)
        self.conn.commit()
        return True, incidents

    def ingest_many(self, assessments: list[RiskAssessment]) -> list[UnifiedIncident]:
        """Persist batch and re-correlate each affected entity once."""
        entities: set[str] = set()
        for assessment in assessments:
            payload = RiskAssessmentTransport.from_entity(assessment).model_dump(mode="json")
            cursor = self.conn.execute(
                "INSERT OR IGNORE INTO risk_assessments (assessment_id, entity_id, domain, event_time, payload) VALUES (?,?,?,?,?)",
                (assessment.assessment_id, assessment.entity_id, assessment.domain,
                 _utc_iso(assessment.event_time) if assessment.event_time else None,
                 json.dumps(payload, sort_keys=True)),
            )
            if cursor.rowcount:
                entities.add(assessment.entity_id)
        for entity_id in entities:
            self._recorrelate_entity(entity_id)
        self.conn.commit()
        return self.list_incidents()

    def _assessments_for_entity(self, entity_id: str) -> list[RiskAssessment]:
        rows = self.conn.execute(
            "SELECT payload FROM risk_assessments WHERE entity_id=? ORDER BY event_time, assessment_id", (entity_id,)
        )
        return [RiskAssessmentTransport.model_validate_json(row["payload"]).to_entity() for row in rows]

    def _recorrelate_entity(self, entity_id: str) -> list[UnifiedIncident]:
        assessments = self._assessments_for_entity(entity_id)
        old = self.conn.execute(
            "SELECT incident_id, assessment_ids FROM temporal_incidents WHERE entity_id=? AND open=1", (entity_id,)
        ).fetchall()
        old_ids = [(row["incident_id"], set(json.loads(row["assessment_ids"]))) for row in old]
        groups = _temporal_groups(assessments, self.config)
        used_old: set[str] = set()
        materialized: list[UnifiedIncident] = []
        for group in groups:
            group_ids = {assessment.assessment_id for assessment in group}
            candidates = [(len(group_ids & prior_ids), incident_id) for incident_id, prior_ids in old_ids
                          if incident_id not in used_old and group_ids & prior_ids]
            incident_id = max(candidates)[1] if candidates else f"INC-{uuid4()}"
            used_old.add(incident_id)
            materialized.append(correlate_window(group, self.config, incident_id))
        self.conn.execute("DELETE FROM temporal_incidents WHERE entity_id=?", (entity_id,))
        for incident in materialized:
            timed = [assessment.event_time for assessment in incident.contributing_assessments if assessment.event_time]
            self.conn.execute(
                "INSERT INTO temporal_incidents (incident_id, entity_id, window_start, window_end, assessment_ids, payload, open) VALUES (?,?,?,?,?,?,1)",
                (incident.incident_id, entity_id,
                 _utc_iso(min(timed)) if timed else None, _utc_iso(max(timed)) if timed else None,
                 json.dumps([assessment.assessment_id for assessment in incident.contributing_assessments]),
                 json.dumps(to_dict(incident), sort_keys=True)),
            )
        return materialized

    def incidents_for_entity(self, entity_id: str) -> list[UnifiedIncident]:
        rows = self.conn.execute(
            "SELECT payload FROM temporal_incidents WHERE entity_id=? AND open=1 ORDER BY window_start, incident_id", (entity_id,)
        )
        return [_incident_from_payload(json.loads(row["payload"])) for row in rows]

    def list_incidents(self) -> list[UnifiedIncident]:
        rows = self.conn.execute("SELECT payload FROM temporal_incidents WHERE open=1")
        incidents = [_incident_from_payload(json.loads(row["payload"])) for row in rows]
        return sorted(incidents, key=lambda incident: incident.combined_score, reverse=True)


def _temporal_groups(assessments: list[RiskAssessment], config: CorrelationConfig) -> list[list[RiskAssessment]]:
    """Partition by fixed windows anchored at earliest event.

    A chain cannot stretch policy window: t=0,119,238 yields two windows, not
    false corroboration between t=0 and t=238.
    """
    timed = sorted((item for item in assessments if item.event_time), key=lambda item: (item.event_time, item.assessment_id))
    untimed = [item for item in assessments if not item.event_time]
    groups: list[list[RiskAssessment]] = []
    cursor = 0
    seconds = config.window_minutes * 60
    while cursor < len(timed):
        start = timed[cursor].event_time
        end = cursor + 1
        while end < len(timed) and (timed[end].event_time - start).total_seconds() <= seconds:
            end += 1
        groups.append(timed[cursor:end])
        cursor = end
    groups.extend([[assessment] for assessment in untimed])
    return groups


def _incident_from_payload(payload: dict) -> UnifiedIncident:
    assessments = [RiskAssessmentTransport.model_validate(item).to_entity() for item in payload["contributing_assessments"]]
    return UnifiedIncident(
        incident_id=payload["incident_id"], entity_id=payload["entity_id"],
        combined_score=payload["combined_score"], contributing_assessments=assessments,
        status=IncidentStatus(payload["status"]),
        access_decision=AccessDecision(payload["access_decision"]) if payload.get("access_decision") else None,
        confidence=payload.get("confidence"), contributing_domains=payload.get("contributing_domains", []),
        created_at=datetime.fromisoformat(payload["created_at"]),
    )
