"""Live behavioral scoring endpoint + end-to-end cross-domain correlation.

Builds a tiny CERT IsolationForest bundle in-fixture (the real joblib artifact is
gitignored), so the endpoint scores a prepared window in-process.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest
import xgboost as xgb
from fastapi.testclient import TestClient
from sklearn.ensemble import IsolationForest
from sklearn.feature_selection import VarianceThreshold
from sklearn.preprocessing import RobustScaler

from backend.app.core.incident_store import IncidentStore
from backend.app.main import create_app
from backend.app.ps2_correlation.correlation_engine import TemporalCorrelationStore
from backend.app.ps2_correlation.fraud_detection import FraudScorer
from ml.models.cert_behavioral_scorer import CertBehavioralScorer
from ml.models.train_cert_behavioral_model import anomaly_scores
from ml.models.train_fraud_model import FEATURE_COLUMNS

KEY = "live-test-key"
T0 = datetime(2031, 1, 1, tzinfo=timezone.utc)

# Two of these are robust-z columns so the scorer can derive explanation reasons.
CERT_FEATURES = ["logon_count_user_robust_z", "file_copy_count_role_robust_z", "off_hours_activity"]


@pytest.fixture
def cert_scorer() -> CertBehavioralScorer:
    rng = np.random.default_rng(0)
    normal = pd.DataFrame(
        {feature: rng.normal(scale=1.0, size=400) for feature in CERT_FEATURES}, columns=CERT_FEATURES,
    )
    selector = VarianceThreshold(0.0).fit(normal)
    scaler = RobustScaler().fit(selector.transform(normal))
    model = IsolationForest(random_state=0, n_estimators=60).fit(scaler.transform(selector.transform(normal)))
    bundle = {
        "variant": "email_enhanced",
        "feature_columns_before_variance_filter": CERT_FEATURES,
        "selected_feature_columns": CERT_FEATURES,
        "selector": selector, "scaler": scaler, "model": model,
    }
    scorer = CertBehavioralScorer(bundle=bundle)
    # Calibrate against the normal population; an extreme window exceeds every
    # knot, so np.interp returns the right edge (1.0) -> above the 0.99 threshold.
    normal_anomaly = np.sort(anomaly_scores(normal, CERT_FEATURES, selector, scaler, model))
    scorer.bundle = {
        **bundle,
        "calibration_knots": normal_anomaly,
        "calibration_percentiles": np.linspace(0.0, 1.0, len(normal_anomaly)),
    }
    return scorer


def _fraud_scorer(tmp_path) -> FraudScorer:
    rng = np.random.default_rng(1)
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


def _client(cert=None, fraud=None) -> TestClient:
    app = create_app(
        store=IncidentStore(":memory:"), temporal_store=TemporalCorrelationStore(":memory:"),
        seed=False, ingestion_api_key=KEY, cert_scorer=cert, fraud_scorer=fraud,
    )
    return TestClient(app)


def _window(entity_id: str, minutes: int, **feature_overrides) -> dict:
    features = {feature: 0.0 for feature in CERT_FEATURES}
    features.update(feature_overrides)
    return {
        "user_id": "VSC6934", "entity_id": entity_id,
        "window_start": (T0 + timedelta(minutes=minutes)).isoformat(),
        "window_end": (T0 + timedelta(minutes=minutes + 60)).isoformat(),
        "event_time": (T0 + timedelta(minutes=minutes)).isoformat(),
        "features": features,
    }


def _post_behavioral(client, body):
    return client.post("/ingest/behavioral", headers={"X-Ingestion-API-Key": KEY}, json=body)


def test_anomalous_window_alerts_and_creates_incident(cert_scorer) -> None:
    client = _client(cert=cert_scorer)
    body = _window("E027", 0, logon_count_user_robust_z=30.0, file_copy_count_role_robust_z=28.0, off_hours_activity=25.0)
    result = _post_behavioral(client, body).json()
    assert result["alerted"] is True
    assert result["domain"] == "ps1_behavioral"
    assert result["entity_id"] == "E027"
    assert result["accepted"] == [result["assessment_id"]]
    assert client.get("/incidents").json()["count"] == 1


def test_normal_window_below_threshold_does_not_alert(cert_scorer) -> None:
    client = _client(cert=cert_scorer)
    result = _post_behavioral(client, _window("E027", 0)).json()
    assert result["alerted"] is False
    assert client.get("/incidents").json()["count"] == 0


def test_end_to_end_cross_domain_corroboration_revokes(cert_scorer, tmp_path) -> None:
    """The money demo: behavioral + transaction for one entity in-window -> revoke."""
    client = _client(cert=cert_scorer, fraud=_fraud_scorer(tmp_path))

    behavioral = _post_behavioral(client, _window(
        "E027", 0, logon_count_user_robust_z=30.0, file_copy_count_role_robust_z=28.0, off_hours_activity=25.0,
    )).json()
    assert behavioral["alerted"] is True

    txn_features = {feature: 0.0 for feature in FEATURE_COLUMNS}
    txn_features.update({"type_TRANSFER": 1.0, "error_balance_orig": 9.0, "is_transfer_then_cashout": 1.0})
    transaction = client.post(
        "/ingest/transaction", headers={"X-Ingestion-API-Key": KEY},
        json={"type": "TRANSFER", "entity_id": "E027", "event_time": (T0 + timedelta(minutes=45)).isoformat(), "features": txn_features},
    ).json()
    assert transaction["scored"] is True

    incident_id = transaction["affected_incident_ids"][0]
    incident = client.get(f"/incidents/{incident_id}").json()
    assert incident["confidence"] == "high"
    assert incident["access_decision"] == "revoke"
    assert incident["contributing_domains"] == ["ps1_behavioral", "ps2_transaction"]
