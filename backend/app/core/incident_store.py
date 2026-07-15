"""SQLite-backed store for UnifiedIncidents with lifecycle + analyst feedback.

Uses only the standard library (no external DB). Holds incidents produced by the
correlation engine, records analyst feedback, drives lifecycle transitions, and
maintains a simple suppression list: when an analyst dismisses an incident for an
entity, future incidents for that entity are flagged `suppressed` — the concrete
"the system gets quieter as analysts give feedback" mechanism.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.app.api.serialize import to_dict
from backend.app.core.lifecycle import apply_action
from backend.app.shared.entities import IncidentStatus, UnifiedIncident

DEFAULT_DB = "data/incidents.db"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class IncidentStore:
    def __init__(self, db_path: str = ":memory:") -> None:
        if db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._init()

    def _init(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS incidents (
                incident_id TEXT PRIMARY KEY,
                entity_id TEXT NOT NULL,
                combined_score REAL,
                confidence TEXT,
                status TEXT,
                access_decision TEXT,
                payload TEXT NOT NULL,
                created_at TEXT
            );
            CREATE TABLE IF NOT EXISTS feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                incident_id TEXT, action TEXT, reason TEXT, analyst TEXT, ts TEXT
            );
            CREATE TABLE IF NOT EXISTS suppressions (
                entity_id TEXT PRIMARY KEY, reason TEXT, ts TEXT
            );
            """
        )
        self.conn.commit()

    # ---- writes ----
    def seed(self, incidents: list[UnifiedIncident]) -> None:
        """Insert incidents that aren't already present (preserves analyst actions)."""
        for inc in incidents:
            self.conn.execute(
                "INSERT OR IGNORE INTO incidents "
                "(incident_id, entity_id, combined_score, confidence, status, access_decision, payload, created_at) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (
                    inc.incident_id, inc.entity_id, inc.combined_score, inc.confidence,
                    inc.status.value, inc.access_decision.value if inc.access_decision else None,
                    json.dumps(to_dict(inc)), _now(),
                ),
            )
        self.conn.commit()

    def record_feedback(self, incident_id: str, action: str, reason: str | None = None,
                        analyst: str = "analyst") -> dict:
        row = self.conn.execute(
            "SELECT entity_id, status FROM incidents WHERE incident_id=?", (incident_id,)
        ).fetchone()
        if row is None:
            raise KeyError(incident_id)
        new_status = apply_action(IncidentStatus(row["status"]), action)  # may raise InvalidTransition
        self.conn.execute("UPDATE incidents SET status=? WHERE incident_id=?", (new_status.value, incident_id))
        self.conn.execute(
            "INSERT INTO feedback (incident_id, action, reason, analyst, ts) VALUES (?,?,?,?,?)",
            (incident_id, action.lower(), reason, analyst, _now()),
        )
        if new_status is IncidentStatus.DISMISSED:
            self.conn.execute(
                "INSERT OR REPLACE INTO suppressions (entity_id, reason, ts) VALUES (?,?,?)",
                (row["entity_id"], reason or "dismissed by analyst", _now()),
            )
        self.conn.commit()
        return self.get_incident(incident_id)

    # ---- reads ----
    def _row_to_dict(self, row: sqlite3.Row) -> dict:
        data: dict[str, Any] = json.loads(row["payload"])
        data["status"] = row["status"]  # column is authoritative for status
        data["suppressed"] = self.is_suppressed(row["entity_id"])
        return data

    def list_incidents(self, status: str | None = None, min_score: float | None = None) -> list[dict]:
        query, params = "SELECT * FROM incidents", []
        clauses = []
        if status:
            clauses.append("status=?"); params.append(status)
        if min_score is not None:
            clauses.append("combined_score>=?"); params.append(min_score)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY combined_score DESC"
        return [self._row_to_dict(r) for r in self.conn.execute(query, params)]

    def get_incident(self, incident_id: str) -> dict:
        row = self.conn.execute("SELECT * FROM incidents WHERE incident_id=?", (incident_id,)).fetchone()
        if row is None:
            raise KeyError(incident_id)
        return self._row_to_dict(row)

    def is_suppressed(self, entity_id: str) -> bool:
        return self.conn.execute(
            "SELECT 1 FROM suppressions WHERE entity_id=?", (entity_id,)
        ).fetchone() is not None

    def suppressed_entities(self) -> list[str]:
        return [r["entity_id"] for r in self.conn.execute("SELECT entity_id FROM suppressions")]

    def feedback_log(self, incident_id: str | None = None) -> list[dict]:
        if incident_id:
            rows = self.conn.execute("SELECT * FROM feedback WHERE incident_id=? ORDER BY id", (incident_id,))
        else:
            rows = self.conn.execute("SELECT * FROM feedback ORDER BY id")
        return [dict(r) for r in rows]
