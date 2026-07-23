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
from backend.app.core.live_scoring import (
    BehavioralWindowIngestRequest,
    TransactionIngestRequest,
    score_and_ingest_behavioral,
    score_and_ingest_transaction,
)
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
    fraud_scorer=None, cert_scorer=None,
) -> FastAPI:
    app = FastAPI(title="VaultWatch Correlation API", version="0.1.0")
    app.state.store = store or IncidentStore(DEFAULT_DB)
    # Production stores share one SQLite file. Separate :memory: connections in
    # tests are intentional and still exercise both persistence boundaries.
    app.state.temporal_store = temporal_store or TemporalCorrelationStore(app.state.store.db_path)
    app.state.ingestion_service = AssessmentIngestionService(app.state.temporal_store, app.state.store)
    app.state.ingestion_api_key = ingestion_api_key if ingestion_api_key is not None else os.getenv("VAULTWATCH_INGESTION_API_KEY")
    app.state.ps1_provider_config = PS1ProviderConfig.from_env()
    # Live scorers are expensive to construct (model + SHAP explainer / joblib
    # bundle), so build once, lazily, on first ingest request. Tests inject tiny
    # models here, mirroring the store/temporal_store injection above.
    app.state.fraud_scorer = fraud_scorer
    app.state.cert_scorer = cert_scorer

    def require_ingestion_key(provided: str | None) -> None:
        configured_key = app.state.ingestion_api_key
        if not configured_key:
            raise HTTPException(status_code=503, detail="assessment ingestion API key is not configured")
        if not provided or not secrets.compare_digest(provided, configured_key):
            raise HTTPException(status_code=401, detail="invalid ingestion API key")

    def get_fraud_scorer():
        if app.state.fraud_scorer is None:
            from backend.app.ps2_correlation.fraud_detection import FraudScorer
            app.state.fraud_scorer = FraudScorer(root=root)
        return app.state.fraud_scorer

    def get_cert_scorer():
        if app.state.cert_scorer is None:
            from ml.models.cert_behavioral_scorer import CertBehavioralScorer
            app.state.cert_scorer = CertBehavioralScorer(root=root)
        return app.state.cert_scorer

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
        require_ingestion_key(x_ingestion_api_key)
        try:
            return app.state.ingestion_service.ingest_envelope(envelope).as_dict()
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))

    @app.post("/ingest/transaction")
    def ingest_transaction(req: TransactionIngestRequest, x_ingestion_api_key: str | None = Header(default=None)) -> dict:
        """Score one prepared PaySim feature row live, then correlate + upsert."""
        require_ingestion_key(x_ingestion_api_key)
        try:
            return score_and_ingest_transaction(get_fraud_scorer(), app.state.ingestion_service, req)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))

    @app.post("/ingest/behavioral")
    def ingest_behavioral(req: BehavioralWindowIngestRequest, x_ingestion_api_key: str | None = Header(default=None)) -> dict:
        """Score one prepared CERT behavioral window live, then correlate + upsert."""
        require_ingestion_key(x_ingestion_api_key)
        try:
            return score_and_ingest_behavioral(get_cert_scorer(), app.state.ingestion_service, req)
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

    @app.get("/demo/live-payloads")
    def demo_live_payloads() -> dict:
        """Serve the committed demo inputs for the live-injection walkthrough.

        These are the same fixtures scripts/demo_live_ingest.py posts. Served so
        the dashboard has one source of truth instead of its own stale copy.
        """
        import json
        from pathlib import Path

        root_path = Path(root)
        out: dict = {}
        for name, rel in (
            ("behavioral", "data/synthetic/live_demo_behavioral_window.json"),
            ("transaction", "data/synthetic/live_demo_transaction.json"),
        ):
            path = root_path / rel
            if not path.exists():
                raise HTTPException(status_code=404, detail=f"demo payload '{name}' not found")
            payload = json.loads(path.read_text(encoding="utf-8"))
            out[name] = {"label": payload.pop("_label", None), "payload": payload}
        return out

    @app.get("/quantum/report")
    def quantum_report() -> dict:
        from pathlib import Path
        inventory_path = Path(root) / DEFAULT_INVENTORY_PATH
        if not inventory_path.exists():
            raise HTTPException(status_code=404, detail="crypto inventory not found")
        return build_report(load_inventory(inventory_path))

    return app


app = create_app()
