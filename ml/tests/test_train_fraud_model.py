"""Tests for the fraud-model training utilities (no dataset required)."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from ml.models.train_fraud_model import (
    FEATURE_COLUMNS,
    LABEL,
    best_f1_threshold,
    time_split,
)

LEAKAGE_COLUMNS = {"isFraud", "isFlaggedFraud", "step", "nameOrig", "nameDest", "entity_id"}


def test_feature_columns_exclude_leakage_and_identifiers() -> None:
    assert LABEL == "isFraud"
    assert LEAKAGE_COLUMNS.isdisjoint(FEATURE_COLUMNS)
    assert len(FEATURE_COLUMNS) == len(set(FEATURE_COLUMNS))  # no dupes


def _synthetic_features(n: int = 1000) -> pd.DataFrame:
    rng = np.random.default_rng(0)
    frame = pd.DataFrame({feature: rng.normal(size=n) for feature in FEATURE_COLUMNS})
    frame["step"] = np.repeat(np.arange(1, 101), n // 100)  # 100 steps, evenly filled
    frame[LABEL] = ((np.arange(n) % 13) == 0).astype(int)  # fraud spread across all steps
    return frame


def test_time_split_is_temporal_and_non_overlapping() -> None:
    train, val, test, train_cut, val_cut = time_split(_synthetic_features(), 0.70, 0.15)

    # Ordered, disjoint step ranges.
    assert train["step"].max() <= train_cut < val["step"].min()
    assert val["step"].max() <= val_cut < test["step"].min()
    assert set(train["step"]).isdisjoint(val["step"])
    assert set(val["step"]).isdisjoint(test["step"])

    # Every split retains fraud positives and roughly the intended ordering of sizes.
    for part in (train, val, test):
        assert part[LABEL].sum() > 0
    assert len(train) > len(val) and len(train) > len(test)


def test_best_f1_threshold_separates_a_clean_signal() -> None:
    y_true = np.array([0, 0, 0, 1, 1, 1])
    proba = np.array([0.05, 0.10, 0.20, 0.80, 0.85, 0.90])
    threshold = best_f1_threshold(y_true, proba)
    assert 0.20 < threshold <= 0.80
    predictions = (proba >= threshold).astype(int)
    assert list(predictions) == list(y_true)  # perfect separation at the chosen threshold
