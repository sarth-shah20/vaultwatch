"""VaultWatch Correlation API."""
from __future__ import annotations

import os
import secrets
from typing import Optional

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

from backend.app.core.assessment_ingestion import AssessmentBatchEnvelope, AssessmentIngestionService
from backend.app.core.incident_store import DEFAULT_DB, IncidentStore
from backend.app.core.lifecycle import ACTION_TO_STATUS, InvalidTransition
from backend.app.ps1_insider_threat.providers import PS1ProviderConfig
from backend.app.ps2_correlation.correlation_engine import TemporalCorrelationStore, build_demo_incidents
from backend.app.quantum_module.crypto_inventory.inventory import (
    DEFAULT_INVENTORY_PATH, build_report, load_inventory,
)


class FeedbackIn(BaseModel):
    action: str
    reason: Optional[str] = None
    analyst: str = "analyst"


def create_app(
    store: Optional[IncidentStore] = None, seed: bool = True, root: str = ".",
    temporal_store: Optional[TemporalCorrelationStore] = None, ingestion_api_key: str | None = None,
) -> FastAPI:
    app = FastAPI(title="VaultWatch Correlation API", version="0.1.0")
    app.state.store = store or IncidentStore(DEFAULT_DB)
    # Production stores share one SQLite file. Separate :memory: connections in
    # tests are intentional and still exercise both persistence boundaries.
    app.state.temporal_store = temporal_store or TemporalCorrelationStore(app.state.store.db_path)
    app.state.ingestion_service = AssessmentIngestionService(app.state.temporal_store, app.state.store)
    app.state.ingestion_api_key = ingestion_api_key if ingestion_api_key is not None else os.getenv("VAULTWATCH_INGESTION_API_KEY")
    app.state.ps1_provider_config = PS1ProviderConfig.from_env()

    if seed:
        try:
            app.state.store.seed(build_demo_incidents(root=root))
        except Exception as exc:
            app.state.seed_error = str(exc)

    @app.get("/providers")
    def providers() -> dict:
        config = app.state.ps1_provider_config
        return {"primary": config.primary, "shadow": config.shadow, "domain": "ps1_behavioral", "shadow_counts_as_corroboration": False}

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok", "incidents": len(app.state.store.list_incidents())}

    @app.post("/assessments")
    def post_assessments(envelope: AssessmentBatchEnvelope, x_ingestion_api_key: str | None = Header(default=None)) -> dict:
        configured_key = app.state.ingestion_api_key
        if not configured_key:
            raise HTTPException(status_code=503, detail="assessment ingestion API key is not configured")
        if not x_ingestion_api_key or not secrets.compare_digest(x_ingestion_api_key, configured_key):
            raise HTTPException(status_code=401, detail="invalid ingestion API key")
        try:
            return app.state.ingestion_service.ingest_envelope(envelope).as_dict()
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))

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
        from pathlib import Path
        inventory_path = Path(root) / DEFAULT_INVENTORY_PATH
        if not inventory_path.exists():
            raise HTTPException(status_code=404, detail="crypto inventory not found")
        return build_report(load_inventory(inventory_path))

    return app


app = create_app()
