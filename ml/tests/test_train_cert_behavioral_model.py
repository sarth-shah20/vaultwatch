"""Tests for chronological unlabeled CERT behavioral model training."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from ml.models.train_cert_behavioral_model import (
    CertTrainingError,
    calibrated_risk,
    calibration_knots,
    chronological_split,
    select_features,
    train_all_variants,
)


def _write_partition(
    root: Path, event_date: str, frame: pd.DataFrame
) -> None:
    path = root / "base" / f"event_date={event_date}"
    path.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(path / "part.parquet", index=False)


def _fixture_feature_root(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "features"
    dates = [f"2010-01-0{day}" for day in range(2, 8)]
    for day_index, event_date in enumerate(dates):
        rows = 12
        frame = pd.DataFrame(
            {
                "user_id": [f"USR{row:04d}" for row in range(rows)],
                "window_start": pd.date_range(
                    f"{event_date} 09:00:00",
                    periods=rows,
                    freq="h",
                    tz="UTC",
                ),
                "event_date": event_date,
                "f_variable": np.arange(rows, dtype=float) + day_index,
                "f_constant": np.ones(rows),
                "logon_count_user_robust_z": np.linspace(-1, 2, rows),
            }
        )
        _write_partition(root, event_date, frame)

    manifest = {
        "ground_truth_used": False,
        "variants": {
            "base": {
                "model_feature_columns": [
                    "f_variable",
                    "f_constant",
                    "logon_count_user_robust_z",
                ]
            }
        },
    }
    manifest_path = tmp_path / "features.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return root, manifest_path


def test_chronological_split_is_disjoint_and_ordered() -> None:
    split = chronological_split(
        ["2010-01-02", "2010-01-03", "2010-01-04", "2010-01-05", "2010-01-06"]
    )

    assert split.train == ("2010-01-02", "2010-01-03", "2010-01-04")
    assert split.validation == ("2010-01-05",)
    assert split.test == ("2010-01-06",)
    assert not (set(split.train) & set(split.test))


def test_variance_filter_removes_constant_training_feature() -> None:
    frame = pd.DataFrame({"variable": [0.0, 1.0, 2.0], "constant": [1.0, 1.0, 1.0]})

    _, selected = select_features(frame, ["variable", "constant"])

    assert selected == ["variable"]


def test_empirical_calibration_is_monotonic() -> None:
    knots, percentiles = calibration_knots(np.array([0.1, 0.2, 0.3, 0.4]))
    risks = calibrated_risk(np.array([0.1, 0.2, 0.3, 0.4]), knots, percentiles)

    assert np.all(np.diff(risks) >= 0)
    assert risks[0] == 0.0
    assert risks[-1] == 1.0


def test_unlabeled_training_writes_model_report_and_snapshot(tmp_path: Path) -> None:
    feature_root, feature_manifest = _fixture_feature_root(tmp_path)
    report_path = tmp_path / "report.json"
    model_dir = tmp_path / "models"
    snapshot_dir = tmp_path / "snapshots"

    report = train_all_variants(
        feature_root=feature_root,
        feature_manifest_path=feature_manifest,
        report_path=report_path,
        variants=("base",),
        train_per_date=12,
        evaluation_per_date=12,
        model_dir=model_dir,
        snapshot_dir=snapshot_dir,
    )

    result = report["variants"]["base"]
    assert report["ground_truth_used"] is False
    assert result["dropped_features"] == ["f_constant"]
    assert result["split"]["train_dates"]["end"] < result["split"]["validation_dates"]["start"]
    assert result["split"]["validation_dates"]["end"] < result["split"]["test_dates"]["start"]
    assert Path(result["model_path"]).is_file()
    assert Path(result["snapshot_path"]).is_file()
    assert report_path.is_file()
    assert result["selection_status"].startswith("experimental_shadow_only")


def test_labeled_manifest_is_rejected(tmp_path: Path) -> None:
    feature_root, feature_manifest = _fixture_feature_root(tmp_path)
    payload = json.loads(feature_manifest.read_text())
    payload["ground_truth_used"] = True
    feature_manifest.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(CertTrainingError, match="unlabeled"):
        train_all_variants(
            feature_root=feature_root,
            feature_manifest_path=feature_manifest,
            report_path=tmp_path / "report.json",
            variants=("base",),
            train_per_date=12,
            evaluation_per_date=12,
            model_dir=tmp_path / "models",
            snapshot_dir=tmp_path / "snapshots",
        )
