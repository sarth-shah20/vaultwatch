"""Build globally-timed CERT + PaySim correlation demo artifacts.

PaySim has no observed wall-clock timestamp. VaultWatch maps step 0 to
2010-01-01T00:00:00Z and adds one hour per step. A deterministic, explicitly
synthetic CERT-user -> PaySim-account bridge is built independently of event
times; scenarios are only pairs that the model finds inside the 120-minute
window under that single clock.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import timedelta
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd

from backend.app.api.serialize import to_dict
from backend.app.ps2_correlation.fraud_detection import FraudScorer
from backend.app.shared.assessment_schema import stable_assessment_id
from backend.app.shared.entities import Reason, RiskAssessment
from backend.app.shared.time_mapping import (
    PAYSIM_STEP_ZERO_UTC,
    PAYSIM_TIME_BASIS,
    PAYSIM_TIME_MAPPING_DESCRIPTION,
)
from ml.data_pipeline.paysim_features import REQUIRED_COLUMNS, build_feature_set
from ml.models.train_cert_behavioral_model import _top_deviations, calibrated_risk

CERT_USERS_PATH = Path("data/raw/cert_insider_threat/users.csv")
PAYSIM_DIR = Path("data/raw/paysim")
CERT_WINDOW_ROOT = Path("data/processed/ps1/cert_behavioral_windows/email_enhanced")
CERT_MODEL_PATH = Path("ml/models/cert_behavioral_email_enhanced.joblib")
BRIDGE_PATH = Path("data/synthetic/cert_paysim_global_demo_crosswalk.json")
SCENARIOS_PATH = Path("data/synthetic/demo_scenarios.json")
CERT_ASSESSMENTS_PATH = Path("data/synthetic/cert_demo_assessments.json")
PS2_ASSESSMENTS_PATH = Path("data/synthetic/ps2_demo_assessments.json")

BRIDGE_VERSION = "global-demo-bridge-v1"
CERT_MODEL_VERSION = "cert-iforest-email-enhanced-v1"
ALERT_RISK_THRESHOLD = 0.99
CORRELATION_WINDOW_MINUTES = 120


def _stable_order(values: list[str]) -> list[str]:
    return sorted(
        values,
        key=lambda value: hashlib.sha256(
            f"{BRIDGE_VERSION}:{value}".encode("utf-8")
        ).hexdigest(),
    )


def _paysim_csv(root: Path) -> Path:
    files = sorted((root / PAYSIM_DIR).glob("*.csv"))
    if not files:
        raise FileNotFoundError(f"No PaySim CSV under {root / PAYSIM_DIR}")
    return files[0]


def load_earliest_fraud_by_account(root: Path) -> pd.DataFrame:
    rows: list[pd.DataFrame] = []
    for chunk in pd.read_csv(
        _paysim_csv(root),
        usecols=["step", "type", "amount", "nameOrig", "isFraud"],
        chunksize=250_000,
    ):
        fraud = chunk[chunk["isFraud"] == 1]
        if not fraud.empty:
            rows.append(fraud)
    if not rows:
        raise ValueError("PaySim source contains no fraud transactions")
    fraud = pd.concat(rows, ignore_index=True)
    fraud = fraud.sort_values(["nameOrig", "step", "amount"], kind="mergesort")
    return fraud.drop_duplicates("nameOrig", keep="first").reset_index(drop=True)


def build_global_bridge(root: Path, fraud: pd.DataFrame) -> dict[str, str]:
    users = pd.read_csv(root / CERT_USERS_PATH, usecols=["user_id"])["user_id"].astype(str).tolist()
    accounts = fraud["nameOrig"].astype(str).tolist()
    if len(accounts) < len(users):
        raise ValueError("Not enough distinct PaySim fraud accounts for deterministic demo bridge")
    bridge = dict(zip(_stable_order(users), _stable_order(accounts)[: len(users)], strict=True))
    payload = {
        "bridge_version": BRIDGE_VERSION,
        "kind": "synthetic_deterministic_cross_dataset_bridge",
        "warning": (
            "CERT users and PaySim accounts have no natural shared identity. This bridge is a deterministic "
            "demo construct independent of timestamps, scores, labels, and transaction amounts."
        ),
        "time_basis": PAYSIM_TIME_BASIS,
        "time_mapping": PAYSIM_TIME_MAPPING_DESCRIPTION,
        "pairs": [
            {"entity_id": f"CERT:{user}", "cert_user": user, "paysim_nameOrig": account}
            for user, account in sorted(bridge.items())
        ],
    }
    (root / BRIDGE_PATH).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return bridge


def score_cert_alerts(root: Path, bridge: dict[str, str], latest_step: int) -> pd.DataFrame:
    bundle = joblib.load(root / CERT_MODEL_PATH)
    columns = list(bundle["selected_feature_columns"])
    z_columns = [c for c in columns if c.endswith("_robust_z")]
    last_date = (pd.Timestamp(PAYSIM_STEP_ZERO_UTC) + pd.Timedelta(hours=int(latest_step))).date()
    frames: list[pd.DataFrame] = []
    for partition in sorted((root / CERT_WINDOW_ROOT).glob("event_date=*")):
        event_date = pd.Timestamp(partition.name.removeprefix("event_date=")).date()
        if event_date > last_date:
            continue
        for file in sorted(partition.glob("*.parquet")):
            frame = pd.read_parquet(
                file, columns=["user_id", "event_time", "window_start", "window_end", *columns]
            )
            frame = frame[frame["user_id"].isin(bridge)]
            if frame.empty:
                continue
            transformed = bundle["scaler"].transform(bundle["selector"].transform(frame[columns]))
            anomaly = -bundle["model"].score_samples(transformed)
            risk = calibrated_risk(anomaly, bundle["calibration_knots"], bundle["calibration_percentiles"])
            alert_mask = risk >= ALERT_RISK_THRESHOLD
            if not alert_mask.any():
                continue
            alerts = frame.loc[alert_mask, ["user_id", "event_time", "window_start", "window_end"]].copy()
            alerts["risk_score"] = risk[alert_mask]
            alerts["top_deviations"] = [
                _top_deviations(row, z_columns)
                for _, row in frame.loc[alert_mask].iterrows()
            ]
            frames.append(alerts)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def match_global_pairs(alerts: pd.DataFrame, fraud: pd.DataFrame, bridge: dict[str, str]) -> pd.DataFrame:
    fraud = fraud.copy()
    fraud["event_time"] = pd.Timestamp(PAYSIM_STEP_ZERO_UTC) + pd.to_timedelta(fraud["step"], unit="h")
    alert = alerts.copy()
    alert["nameOrig"] = alert["user_id"].map(bridge)
    pairs = alert.merge(fraud, on="nameOrig", suffixes=("_cert", "_paysim"))
    pairs["gap_minutes"] = (
        (pairs["event_time_cert"] - pairs["event_time_paysim"]).abs().dt.total_seconds() / 60
    )
    pairs = pairs[pairs["gap_minutes"] <= CORRELATION_WINDOW_MINUTES]
    pairs = pairs.sort_values(["user_id", "gap_minutes", "risk_score"], ascending=[True, True, False])
    return pairs.drop_duplicates("user_id", keep="first").reset_index(drop=True)


def _selected_raw_transactions(root: Path, pairs: pd.DataFrame) -> pd.DataFrame:
    accounts = set(pairs["nameOrig"].astype(str))
    frames: list[pd.DataFrame] = []
    row_offset = 0
    for chunk in pd.read_csv(_paysim_csv(root), usecols=list(REQUIRED_COLUMNS), chunksize=250_000):
        chunk["_source_row"] = np.arange(row_offset, row_offset + len(chunk), dtype=np.int64)
        row_offset += len(chunk)
        selected = chunk[chunk["nameOrig"].isin(accounts)]
        if not selected.empty:
            frames.append(selected)
    raw = pd.concat(frames, ignore_index=True)
    selected_keys = pairs[["nameOrig", "step", "amount"]].drop_duplicates()
    raw = raw.merge(selected_keys, on=["nameOrig", "step", "amount"], how="inner")
    return raw


def build_assessments(root: Path, pairs: pd.DataFrame) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    cert_assessments: list[dict[str, Any]] = []
    for row in pairs.itertuples(index=False):
        entity_id = f"CERT:{row.user_id}"
        reasons = [
            Reason(
                signal_name=f"behavioral_deviation:{item['feature']}",
                domain="ps1_behavioral",
                weight=round(min(1.0, float(row.risk_score) / max(1, len(row.top_deviations))), 4),
                raw_value=(
                    f"{item['baseline']} robust-z={item['robust_z']:.3f} in CERT user-hour window"
                ),
            )
            for item in row.top_deviations
        ]
        if not reasons:
            reasons = [
                Reason(
                    signal_name="isolation_forest_behavioral_anomaly",
                    domain="ps1_behavioral",
                    weight=round(float(row.risk_score), 4),
                    raw_value="Isolation Forest exceeded the operational alert threshold; no non-zero robust-z feature was available.",
                )
            ]
        assessment = RiskAssessment(
            entity_id=entity_id, score=float(row.risk_score), reasons=reasons,
            assessment_id=stable_assessment_id("cert", entity_id, row.event_time_cert.to_pydatetime(), CERT_MODEL_VERSION),
            schema_version="1.0", domain="ps1_behavioral",
            event_time=row.event_time_cert.to_pydatetime(),
            window_start=row.window_start.to_pydatetime(), window_end=row.window_end.to_pydatetime(),
            time_basis="cert_simulated_local_utc", source="cert_r4.2", model_version=CERT_MODEL_VERSION,
        )
        cert_assessments.append(to_dict(assessment))

    raw = _selected_raw_transactions(root, pairs)
    entity_map = {str(row.nameOrig): f"CERT:{row.user_id}" for row in pairs.itertuples(index=False)}
    features = build_feature_set(raw, entity_map=entity_map)
    scorer = FraudScorer(root=root)
    ps2_assessments: list[dict[str, Any]] = []
    for row in pairs.itertuples(index=False):
        selected = features[(features["nameOrig"] == row.nameOrig) & (features["step"] == row.step) & (features["amount"] == row.amount)]
        if len(selected) != 1:
            raise ValueError(f"Expected one selected PaySim transaction for {row.user_id}; got {len(selected)}")
        assessment = scorer.score_row(selected.iloc[0].to_dict(), entity_id=f"CERT:{row.user_id}")
        if assessment is None:
            raise ValueError(f"Selected fraud transaction was not scoreable for {row.user_id}")
        ps2_assessments.append(to_dict(assessment))
    return cert_assessments, ps2_assessments


def build_scenarios(pairs: pd.DataFrame) -> list[dict[str, Any]]:
    scenarios: list[dict[str, Any]] = []
    for index, row in enumerate(
        pairs.sort_values(["risk_score", "gap_minutes"], ascending=[False, True]).itertuples(index=False), start=1
    ):
        scenarios.append({
            "scenario_id": f"GLOBAL-{index:02d}",
            "entity_id": f"CERT:{row.user_id}",
            "cert_user": row.user_id,
            "paysim_account": row.nameOrig,
            "selection": "model-scored CERT alert + real PaySim fraud transaction within global 120-minute window",
            "cert_assessment": {
                "event_time": row.event_time_cert.isoformat(), "window_start": row.window_start.isoformat(),
                "window_end": row.window_end.isoformat(), "risk_score": float(row.risk_score),
                "top_deviations": row.top_deviations,
            },
            "paysim_transaction": {
                "event_time": row.event_time_paysim.isoformat(), "time_basis": PAYSIM_TIME_BASIS,
                "step": int(row.step), "type": row.type, "amount": float(row.amount), "isFraud": 1,
            },
            "gap_minutes": round(float(row.gap_minutes), 3),
        })
    return scenarios


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".")
    args = parser.parse_args()
    root = Path(args.root).resolve()
    fraud = load_earliest_fraud_by_account(root)
    bridge = build_global_bridge(root, fraud)
    alerts = score_cert_alerts(root, bridge, int(fraud["step"].max()))
    pairs = match_global_pairs(alerts, fraud, bridge)
    cert_assessments, ps2_assessments = build_assessments(root, pairs)
    scenarios = build_scenarios(pairs)
    metadata = {
        "generated_by": "global CERT/PaySim model correlation candidate builder",
        "time_basis": PAYSIM_TIME_BASIS,
        "time_mapping": PAYSIM_TIME_MAPPING_DESCRIPTION,
        "correlation_window_minutes": CORRELATION_WINDOW_MINUTES,
        "bridge": "deterministic synthetic cross-dataset bridge; independent of timestamps and model scores",
    }
    (root / CERT_ASSESSMENTS_PATH).write_text(json.dumps({**metadata, "assessments": cert_assessments}, indent=2) + "\n", encoding="utf-8")
    (root / PS2_ASSESSMENTS_PATH).write_text(json.dumps({**metadata, "assessments": ps2_assessments}, indent=2) + "\n", encoding="utf-8")
    (root / SCENARIOS_PATH).write_text(json.dumps({**metadata, "summary": {"scenarios": len(scenarios)}, "scenarios": scenarios}, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(scenarios)} global-clock scenarios")
    for scenario in scenarios:
        print(f"  {scenario['scenario_id']} {scenario['entity_id']} gap={scenario['gap_minutes']}m")


if __name__ == "__main__":
    main()
