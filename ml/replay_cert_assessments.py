"""Score prepared CERT windows and publish versioned PS1 assessments.

This replays scored windows through HTTP or Kafka. It is not raw CERT CSV
streaming and must not be described as real-time raw-log ingestion.

Example:
  VAULTWATCH_INGESTION_API_KEY=... .venv/bin/python -m ml.replay_cert_assessments \
    --date 2011-01-01 --transport http
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Iterable

import httpx
import joblib
import pandas as pd

from backend.app.core.assessment_ingestion import AssessmentBatchEnvelope
from backend.app.shared.assessment_schema import RiskAssessmentTransport, stable_assessment_id
from backend.app.shared.entities import Reason, RiskAssessment
from ml.models.train_cert_behavioral_model import (
    ALERT_RISK_THRESHOLD, DEFAULT_FEATURE_ROOT, _top_deviations, anomaly_scores,
    calibrated_risk, list_dates, load_partition,
)

DOMAIN = "ps1_behavioral"
MODEL_VERSION = "cert-behavioral-email-enhanced-v1"


def score_date(feature_root: Path, model_path: Path, event_date: str, limit: int | None = None) -> list[RiskAssessment]:
    """Score one prepared user-hour partition and retain operational alerts."""
    bundle = joblib.load(model_path)
    features = bundle["feature_columns_before_variance_filter"]
    z_columns = [name for name in features if name.endswith(("_user_robust_z", "_role_robust_z"))]
    frame = load_partition(feature_root / bundle["variant"], event_date,
                           ["user_id", "window_start", "window_end", "event_time", *features])
    if limit:
        frame = frame.head(limit)
    risk = calibrated_risk(anomaly_scores(frame, features, bundle["selector"], bundle["scaler"], bundle["model"]),
                           bundle["calibration_knots"], bundle["calibration_percentiles"])
    results: list[RiskAssessment] = []
    for index, (_, row) in enumerate(frame.iterrows()):
        if risk[index] < ALERT_RISK_THRESHOLD:
            continue
        user = str(row["user_id"])
        event_time = pd.Timestamp(row["event_time"]).to_pydatetime()
        score = float(risk[index])
        deviations = _top_deviations(row, z_columns)
        reasons = [Reason(
            signal_name=item["feature"], domain=DOMAIN, weight=min(1.0, abs(item["robust_z"]) / 25.0),
            raw_value=f"{item['baseline']} robust-z={item['robust_z']:.3f}",
        ) for item in deviations] or [Reason("behavioral_anomaly", DOMAIN, score, "Isolation Forest alert")]
        entity_id = f"CERT:{user}"
        results.append(RiskAssessment(
            assessment_id=stable_assessment_id("cert", entity_id, event_time, MODEL_VERSION),
            entity_id=entity_id, domain=DOMAIN, score=score, reasons=reasons,
            event_time=event_time, window_start=pd.Timestamp(row["window_start"]).to_pydatetime(),
            window_end=pd.Timestamp(row["window_end"]).to_pydatetime(),
            time_basis="cert_simulated_local_utc", source="cert_r4.2_prepared_windows",
            model_version=MODEL_VERSION,
        ))
    return results


def envelope(assessments: Iterable[RiskAssessment]) -> dict:
    return AssessmentBatchEnvelope(assessments=[RiskAssessmentTransport.from_entity(item).model_dump(mode="json") for item in assessments]).model_dump(mode="json")


def publish_http(payload: dict, endpoint: str, api_key: str) -> dict:
    response = httpx.post(endpoint, json=payload, headers={"X-Ingestion-API-Key": api_key}, timeout=30)
    response.raise_for_status()
    return response.json()


def publish_kafka(payload: dict, bootstrap_servers: str) -> None:
    try:
        from kafka import KafkaProducer
    except ImportError as exc:
        raise RuntimeError("Kafka replay requires kafka-python") from exc
    producer = KafkaProducer(bootstrap_servers=bootstrap_servers, value_serializer=lambda value: json.dumps(value).encode())
    producer.send("vaultwatch.risk-assessments.v1", payload).get(timeout=30)
    producer.flush()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--feature-root", type=Path, default=DEFAULT_FEATURE_ROOT)
    parser.add_argument("--model", type=Path, default=Path("ml/models/cert_behavioral_email_enhanced.joblib"))
    parser.add_argument("--date", action="append", help="prepared event_date partition; repeatable")
    parser.add_argument("--limit", type=int, default=None, help="max windows per selected date")
    parser.add_argument("--transport", choices=("http", "kafka"), default="http")
    parser.add_argument("--endpoint", default="http://127.0.0.1:8000/assessments")
    parser.add_argument("--bootstrap-servers", default="localhost:9092")
    args = parser.parse_args()
    dates = args.date or list_dates(args.feature_root / "email_enhanced")
    assessments = [item for date in dates for item in score_date(args.feature_root, args.model, date, args.limit)]
    if not assessments:
        print(json.dumps({"published": 0, "note": "no windows met alert threshold"}))
        return
    payload = envelope(assessments)
    if args.transport == "http":
        key = os.getenv("VAULTWATCH_INGESTION_API_KEY")
        if not key:
            raise SystemExit("VAULTWATCH_INGESTION_API_KEY is required for HTTP replay")
        result = publish_http(payload, args.endpoint, key)
        print(json.dumps(result, indent=2))
    else:
        publish_kafka(payload, args.bootstrap_servers)
        print(json.dumps({"published": len(assessments), "topic": "vaultwatch.risk-assessments.v1"}))


if __name__ == "__main__":
    main()
