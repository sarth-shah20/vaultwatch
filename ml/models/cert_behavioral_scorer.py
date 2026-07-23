"""Reusable in-process CERT behavioral scorer.

Lifted out of ``ml/replay_cert_assessments.py`` so the same scoring path serves
both the offline replay CLI and the live ``POST /ingest/behavioral`` endpoint.
It calls the exact training-time functions (``anomaly_scores`` /
``calibrated_risk`` / ``_top_deviations``) so a live window scores identically to
the replayed one.

Honesty boundary: this runs model INFERENCE live. Raw CERT CSV normalization,
user-hour windowing, and 30-day rolling baselines remain an offline batch stage;
the input here is a prepared behavioral window, not a raw logon line.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

import joblib
import pandas as pd

from backend.app.shared.assessment_schema import stable_assessment_id
from backend.app.shared.entities import Reason, RiskAssessment
from ml.models.train_cert_behavioral_model import (
    ALERT_RISK_THRESHOLD,
    _top_deviations,
    anomaly_scores,
    calibrated_risk,
)

DOMAIN = "ps1_behavioral"
DEFAULT_MODEL_REL_PATH = "ml/models/cert_behavioral_email_enhanced.joblib"
SOURCE = "cert_live_window"


def _parse_dt(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, pd.Timestamp):
        return value.to_pydatetime()
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _num(value: Any) -> float:
    """Coerce a possibly-missing feature to float; missing/NaN -> 0.0 (cold start)."""
    if value is None:
        return 0.0
    try:
        if pd.isna(value):
            return 0.0
    except (TypeError, ValueError):
        pass
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


class CertBehavioralScorer:
    """Loads the trained CERT IsolationForest bundle once and scores windows."""

    def __init__(
        self,
        root: str | Path = ".",
        model_path: str | None = None,
        bundle: Mapping[str, Any] | None = None,
        source: str = SOURCE,
    ) -> None:
        if bundle is None:
            path = Path(root) / (model_path or DEFAULT_MODEL_REL_PATH)
            bundle = joblib.load(path)
        self.bundle = bundle
        self.source = source
        self.features: list[str] = list(bundle["feature_columns_before_variance_filter"])
        self.z_columns = [
            name for name in self.features
            if name.endswith(("_user_robust_z", "_role_robust_z"))
        ]
        variant = str(bundle.get("variant", "unknown")).replace("_", "-")
        self.model_version = f"cert-behavioral-{variant}-v1"

    def _risk(self, frame: pd.DataFrame):
        anomaly = anomaly_scores(
            frame, self.features, self.bundle["selector"], self.bundle["scaler"], self.bundle["model"],
        )
        return calibrated_risk(
            anomaly, self.bundle["calibration_knots"], self.bundle["calibration_percentiles"],
        )

    def _build(self, row: Mapping[str, Any], risk: float, entity_id: str | None) -> RiskAssessment:
        user = str(row.get("user_id", "unknown"))
        series = pd.Series({col: _num(row.get(col)) for col in self.features})
        deviations = _top_deviations(series, self.z_columns)
        reasons = [
            Reason(
                signal_name=item["feature"], domain=DOMAIN,
                weight=min(1.0, abs(item["robust_z"]) / 25.0),
                raw_value=f"{item['baseline']} robust-z={item['robust_z']:.3f}",
            )
            for item in deviations
        ] or [Reason("behavioral_anomaly", DOMAIN, risk, "Isolation Forest alert")]
        resolved = entity_id or f"CERT:{user}"
        event_time = _parse_dt(row.get("event_time"))
        return RiskAssessment(
            assessment_id=stable_assessment_id("cert", resolved, event_time, self.model_version),
            entity_id=resolved, domain=DOMAIN, score=risk, reasons=reasons,
            event_time=event_time, window_start=_parse_dt(row.get("window_start")),
            window_end=_parse_dt(row.get("window_end")),
            time_basis="cert_simulated_local_utc", source=self.source, model_version=self.model_version,
        )

    def score_window(self, window: Mapping[str, Any], entity_id: str | None = None) -> RiskAssessment | None:
        """Score one prepared behavioral window; None if below the alert threshold.

        Missing model feature columns default to 0.0 (documented cold-start
        convention). ``entity_id`` overrides the default ``CERT:<user_id>``.
        """
        row = {col: _num(window.get(col)) for col in self.features}
        frame = pd.DataFrame([row], columns=self.features)
        risk = float(self._risk(frame)[0])
        if risk < ALERT_RISK_THRESHOLD:
            return None
        return self._build(window, risk, entity_id)

    def score_frame(self, frame: pd.DataFrame) -> list[RiskAssessment]:
        """Vectorized scoring of a prepared partition; retains alerts only.

        Used by the offline replay CLI. Uses the default ``CERT:<user_id>``
        identity (no canonical mapping), matching prior replay behavior.
        """
        risk = self._risk(frame)
        results: list[RiskAssessment] = []
        for index, (_, row) in enumerate(frame.iterrows()):
            value = float(risk[index])
            if value < ALERT_RISK_THRESHOLD:
                continue
            results.append(self._build(row, value, None))
        return results
