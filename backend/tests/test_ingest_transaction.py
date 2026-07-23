"""Live transaction scoring endpoint: server scores a raw feature row in-process."""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest
import xgboost as xgb
from fastapi.testclient import TestClient

from backend.app.core.incident_store import IncidentStore
from backend.app.main import create_app
from backend.app.ps2_correlation.correlation_engine import TemporalCorrelationStore
from backend.app.ps2_correlation.fraud_detection import FraudScorer
from ml.models.train_fraud_model import FEATURE_COLUMNS

KEY = "live-test-key"


@pytest.fixture
def fraud_scorer(tmp_path) -> FraudScorer:
    """Train a small, separable model over the real feature columns (as in test_fraud_scorer)."""
    rng = np.random.default_rng(0)
    n = 800
    x = pd.DataFrame({feature: rng.normal(size=n) for feature in FEATURE_COLUMNS})
    y = ((x["error_balance_orig"] > 0.3) | (x["is_transfer_then_cashout"] > 0.5)).astype(int)
    model = xgb.XGBClassifier(n_estimators=40, max_depth=3, eval_metric="logloss", random_state=0, n_jobs=1)
    model.fit(x, y)
    (tmp_path / "ml/models").mkdir(parents=True)
    model.save_model(str(tmp_path / "ml/models/fraud_model.json"))
    (tmp_path / "ml/models/fraud_model_meta.json").write_text(
        json.dumps({"features": FEATURE_COLUMNS, "threshold": 0.5}), encoding="utf-8"
    )
    return FraudScorer(root=tmp_path)


def _client(scorer: FraudScorer, key: str | None = KEY) -> TestClient:
    app = create_app(
        store=IncidentStore(":memory:"), temporal_store=TemporalCorrelationStore(":memory:"),
        seed=False, ingestion_api_key=key, fraud_scorer=scorer,
    )
    return TestClient(app)


def _features(**overrides) -> dict:
    row = {feature: 0.0 for feature in FEATURE_COLUMNS}
    row["type_TRANSFER"] = 1.0
    row.update(overrides)
    return row


def _post(client: TestClient, body: dict, key: str = KEY):
    return client.post("/ingest/transaction", headers={"X-Ingestion-API-Key": key}, json=body)


def test_eligible_transfer_is_scored_and_creates_incident(fraud_scorer) -> None:
    client = _client(fraud_scorer)
    body = {
        "type": "TRANSFER", "entity_id": "E027", "step": 5,
        "features": _features(error_balance_orig=9.0, is_transfer_then_cashout=1.0),
    }
    result = _post(client, body).json()
    assert result["scored"] is True
    assert 0.0 <= result["score"] <= 1.0
    assert result["entity_id"] == "E027"
    assert result["domain"] == "ps2_transaction"
    assert result["accepted"] == [result["assessment_id"]]
    assert result["affected_incident_ids"]
    incidents = client.get("/incidents").json()["incidents"]
    assert any(inc["entity_id"] == "E027" for inc in incidents)


def test_ineligible_type_is_not_scored(fraud_scorer) -> None:
    client = _client(fraud_scorer)
    body = {"type": "PAYMENT", "entity_id": "E010", "features": _features(type_TRANSFER=0.0)}
    result = _post(client, body).json()
    assert result["scored"] is False
    assert client.get("/incidents").json()["count"] == 0


def test_wrong_key_is_rejected(fraud_scorer) -> None:
    client = _client(fraud_scorer)
    assert _post(client, {"type": "TRANSFER", "features": _features()}, key="nope").status_code == 401


def test_unconfigured_key_returns_503(fraud_scorer) -> None:
    client = _client(fraud_scorer, key="")
    assert _post(client, {"type": "TRANSFER", "features": _features()}).status_code == 503


def test_malformed_body_returns_422(fraud_scorer) -> None:
    client = _client(fraud_scorer)
    # missing required "type"
    assert client.post("/ingest/transaction", headers={"X-Ingestion-API-Key": KEY}, json={"features": {}}).status_code == 422
