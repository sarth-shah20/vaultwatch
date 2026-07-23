"""Train unlabeled CERT behavioral anomaly models.

No answer key or labels are read. Both feature variants use chronological date
splits, train-only variance filtering/scaling, deterministic Isolation Forest,
and empirical validation-percentile risk calibration.

Run:
    .venv/bin/python3 -m ml.models.train_cert_behavioral_model
"""

from __future__ import annotations

import argparse
import heapq
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.feature_selection import VarianceThreshold
from sklearn.preprocessing import RobustScaler

DEFAULT_FEATURE_ROOT = Path("data/processed/ps1/cert_behavioral_windows")
DEFAULT_FEATURE_MANIFEST = Path(
    "data/manifests/ps1_cert_behavioral_features.json"
)
DEFAULT_REPORT_PATH = Path("data/manifests/ps1_cert_training_report.json")
DEFAULT_MODEL_DIR = Path("ml/models")
DEFAULT_SNAPSHOT_DIR = Path("data/processed/ps1/cert_model")
SEED = 42
TRAIN_FRACTION = 0.60
VALIDATION_FRACTION = 0.20
TRAIN_SAMPLE_PER_DATE = 800
EVALUATION_SAMPLE_PER_DATE = 2_000
MAX_SAMPLES = 50_000
N_ESTIMATORS = 150
ALERT_RISK_THRESHOLD = 0.99


class CertTrainingError(ValueError):
    """Raised when behavioral feature inputs violate training contract."""


@dataclass(frozen=True)
class DateSplit:
    """Chronological split with disjoint UTC calendar dates."""

    train: tuple[str, ...]
    validation: tuple[str, ...]
    test: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "strategy": "chronological_date",
            "train_dates": {"start": self.train[0], "end": self.train[-1], "count": len(self.train)},
            "validation_dates": {
                "start": self.validation[0],
                "end": self.validation[-1],
                "count": len(self.validation),
            },
            "test_dates": {"start": self.test[0], "end": self.test[-1], "count": len(self.test)},
        }


def list_dates(variant_root: Path) -> list[str]:
    dates = sorted(
        path.name.removeprefix("event_date=")
        for path in variant_root.glob("event_date=*")
        if path.is_dir()
    )
    if len(dates) < 5:
        raise CertTrainingError(
            f"Need at least five partitions for chronological split: {variant_root}"
        )
    return dates


def chronological_split(
    dates: list[str],
    train_fraction: float = TRAIN_FRACTION,
    validation_fraction: float = VALIDATION_FRACTION,
) -> DateSplit:
    if not 0 < train_fraction < 1 or not 0 < validation_fraction < 1:
        raise ValueError("split fractions must be in (0, 1)")
    if train_fraction + validation_fraction >= 1:
        raise ValueError("train + validation fractions must be below 1")
    ordered = tuple(sorted(dates))
    train_end = int(len(ordered) * train_fraction)
    validation_end = train_end + int(len(ordered) * validation_fraction)
    split = DateSplit(
        train=ordered[:train_end],
        validation=ordered[train_end:validation_end],
        test=ordered[validation_end:],
    )
    if not all((split.train, split.validation, split.test)):
        raise CertTrainingError("chronological split produced an empty section")
    if set(split.train) & set(split.validation) or set(split.validation) & set(split.test):
        raise CertTrainingError("chronological split overlaps dates")
    if not split.train[-1] < split.validation[0] < split.test[0]:
        raise CertTrainingError("chronological split is not strictly ordered")
    return split


def _partition_files(variant_root: Path, event_date: str) -> list[Path]:
    files = sorted((variant_root / f"event_date={event_date}").glob("*.parquet"))
    if not files:
        raise CertTrainingError(
            f"Missing feature partition for {event_date}: {variant_root}"
        )
    return files


def load_partition(
    variant_root: Path,
    event_date: str,
    columns: list[str],
) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    optional = {"window_end", "event_time"}
    for path in _partition_files(variant_root, event_date):
        try:
            frame = pd.read_parquet(path, columns=columns)
        except Exception as exc:
            # Step 2 fixtures may predate timestamp boundary columns. Preserve
            # training compatibility, then derive conservative window timestamps.
            if not optional.intersection(columns) or "No match for FieldRef.Name" not in str(exc):
                raise
            available = [column for column in columns if column not in optional]
            frame = pd.read_parquet(path, columns=available)
        frames.append(frame)
    result = pd.concat(frames, ignore_index=True)
    if "window_end" in columns and "window_end" not in result:
        result["window_end"] = pd.to_datetime(result["window_start"]) + pd.Timedelta(hours=1)
    if "event_time" in columns and "event_time" not in result:
        result["event_time"] = result["window_end"]
    return result


def stratified_date_sample(
    variant_root: Path,
    dates: Iterable[str],
    columns: list[str],
    *,
    sample_per_date: int,
    seed: int,
) -> pd.DataFrame:
    samples: list[pd.DataFrame] = []
    for index, event_date in enumerate(dates):
        frame = load_partition(variant_root, event_date, columns)
        size = min(len(frame), sample_per_date)
        if size < len(frame):
            frame = frame.sample(n=size, random_state=seed + index)
        samples.append(frame)
    if not samples:
        raise CertTrainingError("sampling received no date partitions")
    return pd.concat(samples, ignore_index=True)


def select_features(
    train_frame: pd.DataFrame,
    feature_columns: list[str],
    threshold: float = 1e-12,
) -> tuple[VarianceThreshold, list[str]]:
    selector = VarianceThreshold(threshold=threshold)
    selector.fit(train_frame[feature_columns])
    selected = [
        column
        for column, keep in zip(feature_columns, selector.get_support())
        if keep
    ]
    if not selected:
        raise CertTrainingError("variance filter removed every model feature")
    return selector, selected


def fit_model(
    train_frame: pd.DataFrame,
    feature_columns: list[str],
    *,
    seed: int = SEED,
) -> tuple[VarianceThreshold, RobustScaler, IsolationForest, list[str]]:
    selector, selected = select_features(train_frame, feature_columns)
    selected_values = selector.transform(train_frame[feature_columns])
    scaler = RobustScaler()
    scaled = scaler.fit_transform(selected_values)
    model = IsolationForest(
        n_estimators=N_ESTIMATORS,
        max_samples=min(MAX_SAMPLES, len(scaled)),
        contamination="auto",
        random_state=seed,
        n_jobs=-1,
    )
    model.fit(scaled)
    return selector, scaler, model, selected


def anomaly_scores(
    frame: pd.DataFrame,
    feature_columns: list[str],
    selector: VarianceThreshold,
    scaler: RobustScaler,
    model: IsolationForest,
) -> np.ndarray:
    values = selector.transform(frame[feature_columns])
    scaled = scaler.transform(values)
    return -model.score_samples(scaled)


def baseline_scores(frame: pd.DataFrame, z_columns: list[str]) -> np.ndarray:
    if not z_columns:
        return np.zeros(len(frame), dtype=float)
    values = frame[z_columns].to_numpy(dtype=float, copy=False)
    return np.max(np.abs(values), axis=1)


def calibration_knots(validation_anomaly_scores: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    if len(validation_anomaly_scores) == 0:
        raise CertTrainingError("validation scoring produced no rows")
    percentiles = np.linspace(0.0, 1.0, 1001)
    knots = np.quantile(validation_anomaly_scores, percentiles)
    knots = np.maximum.accumulate(knots)
    return knots, percentiles


def calibrated_risk(
    anomaly: np.ndarray,
    knots: np.ndarray,
    percentiles: np.ndarray,
) -> np.ndarray:
    return np.interp(anomaly, knots, percentiles, left=0.0, right=1.0)


def distribution_summary(values: np.ndarray) -> dict[str, float]:
    return {
        "mean": float(np.mean(values)),
        "std": float(np.std(values)),
        "p50": float(np.quantile(values, 0.50)),
        "p95": float(np.quantile(values, 0.95)),
        "p99": float(np.quantile(values, 0.99)),
        "min": float(np.min(values)),
        "max": float(np.max(values)),
    }


def _top_deviations(row: pd.Series, z_columns: list[str], top_k: int = 3) -> list[dict[str, Any]]:
    ranked = sorted(
        (
            (column, float(row[column]))
            for column in z_columns
            if float(row[column]) != 0.0
        ),
        key=lambda item: abs(item[1]),
        reverse=True,
    )[:top_k]
    return [
        {
            "feature": column.removesuffix("_user_robust_z").removesuffix("_role_robust_z"),
            "baseline": "user" if column.endswith("_user_robust_z") else "role",
            "robust_z": value,
        }
        for column, value in ranked
    ]


def evaluate_split(
    variant_root: Path,
    dates: tuple[str, ...],
    *,
    feature_columns: list[str],
    z_columns: list[str],
    selector: VarianceThreshold,
    scaler: RobustScaler,
    model: IsolationForest,
    knots: np.ndarray,
    percentiles: np.ndarray,
    sample_per_date: int,
    seed: int,
    capture_examples: bool = False,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    requested = ["user_id", "window_start", "window_end", "event_time", "event_date", *feature_columns]
    raw_scores: list[np.ndarray] = []
    baseline: list[np.ndarray] = []
    risks: list[np.ndarray] = []
    daily_alert_rates: list[float] = []
    examples: list[tuple[float, int, dict[str, Any]]] = []
    example_counter = 0

    for index, event_date in enumerate(dates):
        frame = load_partition(variant_root, event_date, requested)
        if len(frame) > sample_per_date:
            frame = frame.sample(n=sample_per_date, random_state=seed + index)
        anomaly = anomaly_scores(frame, feature_columns, selector, scaler, model)
        risk = calibrated_risk(anomaly, knots, percentiles)
        z_score = baseline_scores(frame, z_columns)
        raw_scores.append(anomaly)
        risks.append(risk)
        baseline.append(z_score)
        daily_alert_rates.append(float(np.mean(risk >= ALERT_RISK_THRESHOLD)))

        if capture_examples:
            for row_index, (_, row) in enumerate(frame.iterrows()):
                record = {
                    "user_id": str(row["user_id"]),
                    "window_start": pd.Timestamp(row["window_start"]).isoformat(),
                    "window_end": pd.Timestamp(row["window_end"]).isoformat(),
                    "event_time": pd.Timestamp(row["event_time"]).isoformat(),
                    "event_date": str(row["event_date"]),
                    "risk_score": float(risk[row_index]),
                    "isolation_forest_anomaly": float(anomaly[row_index]),
                    "robust_z_baseline": float(z_score[row_index]),
                    "top_deviations": _top_deviations(row, z_columns),
                }
                heapq.heappush(examples, (float(risk[row_index]), example_counter, record))
                example_counter += 1
                if len(examples) > 100:
                    heapq.heappop(examples)

    anomaly_values = np.concatenate(raw_scores)
    risk_values = np.concatenate(risks)
    baseline_values = np.concatenate(baseline)
    correlation = (
        float(np.corrcoef(anomaly_values, baseline_values)[0, 1])
        if np.std(anomaly_values) > 0 and np.std(baseline_values) > 0
        else 0.0
    )
    mean_rate = float(np.mean(daily_alert_rates))
    stability = (
        float(np.std(daily_alert_rates) / mean_rate)
        if mean_rate > 0
        else 0.0
    )
    metrics = {
        "rows_sampled": int(len(risk_values)),
        "anomaly_score": distribution_summary(anomaly_values),
        "risk_score": distribution_summary(risk_values),
        "robust_z_baseline": distribution_summary(baseline_values),
        "alert_risk_threshold": ALERT_RISK_THRESHOLD,
        "alert_rate": float(np.mean(risk_values >= ALERT_RISK_THRESHOLD)),
        "daily_alert_rate_coefficient_of_variation": stability,
        "if_to_z_score_correlation": correlation,
        "evaluation_sampling": {
            "stratified_by": "event_date",
            "maximum_rows_per_date": sample_per_date,
            "seed": seed,
        },
    }
    ordered_examples = [record for _, _, record in sorted(examples, reverse=True)]
    return metrics, ordered_examples


def perturbation_sensitivity(
    variant_root: Path,
    dates: tuple[str, ...],
    *,
    feature_columns: list[str],
    selector: VarianceThreshold,
    scaler: RobustScaler,
    model: IsolationForest,
    knots: np.ndarray,
    percentiles: np.ndarray,
    seed: int,
) -> dict[str, Any]:
    frame = stratified_date_sample(
        variant_root,
        dates[:min(10, len(dates))],
        ["user_id", *feature_columns],
        sample_per_date=500,
        seed=seed,
    )
    original = calibrated_risk(
        anomaly_scores(frame, feature_columns, selector, scaler, model),
        knots,
        percentiles,
    )
    perturbed = frame.copy()
    changed: list[str] = []
    for column in (
        "logon_count",
        "new_logon_pc_count",
        "file_to_removable_count",
        "email_external_recipient_ratio",
        "email_attachment_bytes",
    ):
        if column in perturbed:
            if "ratio" in column:
                perturbed[column] = 1.0
            elif "bytes" in column:
                perturbed[column] = perturbed[column].astype(float) + 1_000_000.0
            else:
                perturbed[column] = perturbed[column].astype(float) + 10.0
            changed.append(column)
    altered = calibrated_risk(
        anomaly_scores(perturbed, feature_columns, selector, scaler, model),
        knots,
        percentiles,
    )
    delta = altered - original
    return {
        "kind": "controlled_feature_perturbation_not_ground_truth_evaluation",
        "rows": int(len(frame)),
        "changed_features": changed,
        "median_risk_delta": float(np.median(delta)),
        "mean_risk_delta": float(np.mean(delta)),
        "fraction_risk_increased": float(np.mean(delta > 0)),
    }


def train_variant(
    feature_root: Path,
    variant: str,
    feature_manifest: dict[str, Any],
    *,
    train_per_date: int,
    evaluation_per_date: int,
    seed: int,
    model_dir: Path,
    snapshot_dir: Path,
) -> dict[str, Any]:
    variant_root = feature_root / variant
    dates = list_dates(variant_root)
    split = chronological_split(dates)
    feature_columns = list(feature_manifest["variants"][variant]["model_feature_columns"])
    z_columns = [column for column in feature_columns if column.endswith("_robust_z")]
    train = stratified_date_sample(
        variant_root,
        split.train,
        feature_columns,
        sample_per_date=train_per_date,
        seed=seed,
    )
    selector, scaler, model, selected = fit_model(train, feature_columns, seed=seed)
    dropped = [column for column in feature_columns if column not in selected]

    validation_sample = stratified_date_sample(
        variant_root,
        split.validation,
        feature_columns,
        sample_per_date=evaluation_per_date,
        seed=seed + 10_000,
    )
    validation_anomaly = anomaly_scores(
        validation_sample, feature_columns, selector, scaler, model
    )
    knots, percentiles = calibration_knots(validation_anomaly)
    validation_metrics, _ = evaluate_split(
        variant_root,
        split.validation,
        feature_columns=feature_columns,
        z_columns=z_columns,
        selector=selector,
        scaler=scaler,
        model=model,
        knots=knots,
        percentiles=percentiles,
        sample_per_date=evaluation_per_date,
        seed=seed + 20_000,
    )
    test_metrics, examples = evaluate_split(
        variant_root,
        split.test,
        feature_columns=feature_columns,
        z_columns=z_columns,
        selector=selector,
        scaler=scaler,
        model=model,
        knots=knots,
        percentiles=percentiles,
        sample_per_date=evaluation_per_date,
        seed=seed + 30_000,
        capture_examples=True,
    )
    perturbation = perturbation_sensitivity(
        variant_root,
        split.test,
        feature_columns=feature_columns,
        selector=selector,
        scaler=scaler,
        model=model,
        knots=knots,
        percentiles=percentiles,
        seed=seed + 40_000,
    )

    model_dir.mkdir(parents=True, exist_ok=True)
    model_path = model_dir / f"cert_behavioral_{variant}.joblib"
    joblib.dump(
        {
            "schema_version": "1.0",
            "variant": variant,
            "feature_columns_before_variance_filter": feature_columns,
            "selected_feature_columns": selected,
            "selector": selector,
            "scaler": scaler,
            "model": model,
            "calibration_knots": knots,
            "calibration_percentiles": percentiles,
            "risk_semantics": "empirical validation-percentile behavioral risk; not calibrated probability",
        },
        model_path,
    )
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    snapshot_path = snapshot_dir / f"cert_{variant}_test_snapshot.json"
    snapshot_path.write_text(
        json.dumps(examples, indent=2) + "\n", encoding="utf-8"
    )
    return {
        "variant": variant,
        "model_path": str(model_path),
        "snapshot_path": str(snapshot_path),
        "feature_counts": {
            "before_variance_filter": len(feature_columns),
            "selected": len(selected),
            "dropped": len(dropped),
        },
        "dropped_features": dropped,
        "split": split.as_dict(),
        "training_sampling": {
            "stratified_by": "event_date",
            "maximum_rows_per_date": train_per_date,
            "rows_sampled": int(len(train)),
            "seed": seed,
        },
        "model": {
            "type": "IsolationForest",
            "n_estimators": N_ESTIMATORS,
            "max_samples": min(MAX_SAMPLES, len(train)),
            "seed": seed,
        },
        "validation": validation_metrics,
        "test": test_metrics,
        "controlled_perturbation": perturbation,
        "selection_status": (
            "experimental_shadow_only; unlabeled metrics are not detection performance"
        ),
    }


def train_all_variants(
    feature_root: Path = DEFAULT_FEATURE_ROOT,
    feature_manifest_path: Path = DEFAULT_FEATURE_MANIFEST,
    report_path: Path = DEFAULT_REPORT_PATH,
    *,
    variants: tuple[str, ...] = ("base", "email_enhanced"),
    train_per_date: int = TRAIN_SAMPLE_PER_DATE,
    evaluation_per_date: int = EVALUATION_SAMPLE_PER_DATE,
    seed: int = SEED,
    model_dir: Path = DEFAULT_MODEL_DIR,
    snapshot_dir: Path = DEFAULT_SNAPSHOT_DIR,
) -> dict[str, Any]:
    feature_manifest = json.loads(feature_manifest_path.read_text(encoding="utf-8"))
    if feature_manifest.get("ground_truth_used") is not False:
        raise CertTrainingError("CERT Step 3 must remain unlabeled")
    results = {}
    for variant in variants:
        if variant not in feature_manifest.get("variants", {}):
            raise CertTrainingError(f"Unknown feature variant: {variant}")
        print(f"Training CERT behavioral variant: {variant}", flush=True)
        results[variant] = train_variant(
            feature_root,
            variant,
            feature_manifest,
            train_per_date=train_per_date,
            evaluation_per_date=evaluation_per_date,
            seed=seed,
            model_dir=model_dir,
            snapshot_dir=snapshot_dir,
        )
    recommended = min(
        results,
        key=lambda name: results[name]["test"][
            "daily_alert_rate_coefficient_of_variation"
        ],
    )
    shadow_selection = {
        "recommended_variant": recommended,
        "basis": "lowest sampled test daily alert-rate coefficient of variation",
        "promotion_status": "shadow-only; unlabeled operational comparison",
    }

    report = {
        "report_version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "unlabeled": True,
        "ground_truth_used": False,
        "input_feature_manifest": str(feature_manifest_path),
        "variants": results,
        "shadow_selection": shadow_selection,
        "limitations": [
            "No labels or ground-truth answer key were used.",
            "Metrics report operational stability and perturbation sensitivity, not recall, precision, PR-AUC, or detection performance.",
            "Scores are empirical validation-percentile behavioral risk, not probabilities.",
            "Models remain experimental/shadow-only until later integration gates pass.",
            "Robust-z baseline may saturate at its configured clip (25); use it as explanation evidence, not independent access-control decision.",
            "The committed alert examples are a deterministic 100-record test snapshot, not the full 173,299-row test population; alert-mix observations from that snapshot must not be generalized without a full-population audit.",
        ],
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--feature-root", type=Path, default=DEFAULT_FEATURE_ROOT)
    parser.add_argument("--feature-manifest", type=Path, default=DEFAULT_FEATURE_MANIFEST)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT_PATH)
    parser.add_argument("--variant", choices=("base", "email_enhanced", "both"), default="both")
    parser.add_argument("--train-per-date", type=int, default=TRAIN_SAMPLE_PER_DATE)
    parser.add_argument("--evaluation-per-date", type=int, default=EVALUATION_SAMPLE_PER_DATE)
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument("--model-dir", type=Path, default=DEFAULT_MODEL_DIR)
    parser.add_argument("--snapshot-dir", type=Path, default=DEFAULT_SNAPSHOT_DIR)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    variants = ("base", "email_enhanced") if args.variant == "both" else (args.variant,)
    report = train_all_variants(
        feature_root=args.feature_root,
        feature_manifest_path=args.feature_manifest,
        report_path=args.report,
        variants=variants,
        train_per_date=args.train_per_date,
        evaluation_per_date=args.evaluation_per_date,
        seed=args.seed,
        model_dir=args.model_dir,
        snapshot_dir=args.snapshot_dir,
    )
    print(
        json.dumps(
            {
                variant: {
                    "selected_features": result["feature_counts"]["selected"],
                    "test_alert_rate": result["test"]["alert_rate"],
                }
                for variant, result in report["variants"].items()
            }
        )
    )


if __name__ == "__main__":
    main()
