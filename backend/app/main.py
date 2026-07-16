"""VaultWatch Correlation API.

Serves UnifiedIncident cases (fused PS1 behavioral + PS2 transactional risk) and
accepts analyst feedback that drives the alert lifecycle.

Run: uvicorn backend.app.main:app --reload   (from the repo root)
"""
from __future__ import annotations

from typing import Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from backend.app.core.incident_store import DEFAULT_DB, IncidentStore
from backend.app.core.lifecycle import ACTION_TO_STATUS, InvalidTransition
from backend.app.ps2_correlation.correlation_engine import build_demo_incidents
from backend.app.quantum_module.crypto_inventory.inventory import (
    DEFAULT_INVENTORY_PATH,
    build_report,
    load_inventory,
)


class FeedbackIn(BaseModel):
    action: str  # acknowledge | dismiss | escalate
    reason: Optional[str] = None
    analyst: str = "analyst"


def create_app(store: Optional[IncidentStore] = None, seed: bool = True, root: str = ".") -> FastAPI:
    app = FastAPI(title="VaultWatch Correlation API", version="0.1.0")
    app.state.store = store or IncidentStore(DEFAULT_DB)

    if seed:
        try:
            app.state.store.seed(build_demo_incidents(root=root))
        except Exception as exc:  # never fail startup if demo artifacts are absent
            app.state.seed_error = str(exc)

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok", "incidents": len(app.state.store.list_incidents())}

    @app.get("/incidents")
    def list_incidents(status: Optional[str] = None, min_score: Optional[float] = None) -> dict:
        items = app.state.store.list_incidents(status=status, min_score=min_score)
        return {"count": len(items), "incidents": items}

    @app.get("/incidents/{incident_id}")
    def get_incident(incident_id: str) -> dict:
        try:
            return app.state.store.get_incident(incident_id)
        except KeyError:
            raise HTTPException(status_code=404, detail=f"incident '{incident_id}' not found")

    @app.get("/incidents/{incident_id}/feedback")
    def incident_feedback(incident_id: str) -> dict:
        return {"feedback": app.state.store.feedback_log(incident_id)}

    @app.post("/incidents/{incident_id}/feedback")
    def post_feedback(incident_id: str, body: FeedbackIn) -> dict:
        if body.action.lower() not in ACTION_TO_STATUS:
            raise HTTPException(status_code=422, detail=f"action must be one of {sorted(ACTION_TO_STATUS)}")
        try:
            return app.state.store.record_feedback(incident_id, body.action, body.reason, body.analyst)
        except KeyError:
            raise HTTPException(status_code=404, detail=f"incident '{incident_id}' not found")
        except InvalidTransition as exc:
            raise HTTPException(status_code=409, detail=str(exc))

    @app.get("/suppressions")
    def suppressions() -> dict:
        return {"suppressed_entities": app.state.store.suppressed_entities()}

    @app.get("/quantum/report")
    def quantum_report() -> dict:
        """Crypto inventory scored for quantum risk: summary + prioritized
        PQC-migration list (HNDL-exposed assets flagged). Computed live from
        the committed inventory so scoring changes are reflected immediately."""
        from pathlib import Path

        inventory_path = Path(root) / DEFAULT_INVENTORY_PATH
        if not inventory_path.exists():
            raise HTTPException(status_code=404, detail="crypto inventory not found")
        return build_report(load_inventory(inventory_path))

    return app


app = create_app()
