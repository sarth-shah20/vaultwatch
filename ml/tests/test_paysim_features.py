"""Tests for PaySim fraud feature engineering."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from ml.data_pipeline.paysim_features import (
    build_feature_set,
    load_entity_mapping,
    load_paysim,
    validate_entity_coverage,
)


def _sample_paysim_frame() -> pd.DataFrame:
    """Create a tiny PaySim-like dataframe with one transfer-cashout pattern."""

    return pd.DataFrame(
        {
            "step": [1, 2, 3, 3, 5, 28],
            "type": ["PAYMENT", "TRANSFER", "CASH_OUT", "PAYMENT", "TRANSFER", "CASH_OUT"],
            "amount": [100.0, 200.0, 50.0, 25.0, 500.0, 300.0],
            "nameOrig": ["C1", "C1", "C1", "C2", "C3", "C1"],
            "oldbalanceOrg": [1000.0, 900.0, 700.0, 400.0, 500.0, 450.0],
            "newbalanceOrig": [900.0, 700.0, 650.0, 375.0, 0.0, 150.0],
            "nameDest": ["M1", "C9", "C10", "M2", "C11", "C12"],
            "oldbalanceDest": [0.0, 1000.0, 200.0, 0.0, 100.0, 400.0],
            "newbalanceDest": [0.0, 1200.0, 250.0, 0.0, 600.0, 700.0],
            "isFraud": [0, 1, 1, 0, 1, 1],
            "isFlaggedFraud": [0, 0, 0, 0, 0, 0],
        }
    )


def test_transaction_features_and_type_encoding() -> None:
    """Row-level balance checks, calendar fields, merchant flag, and dummies are correct."""

    features = build_feature_set(_sample_paysim_frame(), {"C1": "E001"}, window=3)

    assert features.loc[0, "error_balance_orig"] == 0.0
    assert features.loc[0, "error_balance_dest"] == 100.0
    assert bool(features.loc[0, "is_merchant_dest"]) is True
    assert bool(features.loc[2, "is_merchant_dest"]) is False
    assert features.loc[5, "hour_of_day"] == 4
    assert features.loc[5, "day_index"] == 1
    assert features.loc[2, "type_CASH_OUT"] == 1
    assert features.loc[2, "type_PAYMENT"] == 0
    assert "nameOrig" in features.columns
    assert "nameDest" in features.columns
    assert features.loc[0, "entity_id"] == "E001"
    assert pd.isna(features.loc[3, "entity_id"])


def test_account_trailing_window_features_include_current_transaction() -> None:
    """Origin-account rolling features use rows in the current trailing step window."""

    features = build_feature_set(_sample_paysim_frame(), {"C1": "E001"}, window=3)

    assert features.loc[0, "orig_txn_count_trailing_window"] == 1
    assert features.loc[0, "orig_total_amount_trailing_window"] == 100.0
    assert features.loc[0, "orig_unique_dest_trailing_window"] == 1
    assert pd.isna(features.loc[0, "orig_steps_since_prev_txn"])
    assert features.loc[0, "amount_to_orig_trailing_avg_amount"] == 1.0

    assert features.loc[2, "orig_txn_count_trailing_window"] == 3
    assert features.loc[2, "orig_total_amount_trailing_window"] == 350.0
    assert features.loc[2, "orig_unique_dest_trailing_window"] == 3
    assert features.loc[2, "orig_steps_since_prev_txn"] == 1
    assert features.loc[2, "amount_to_orig_trailing_avg_amount"] == 50.0 / (350.0 / 3.0)

    assert features.loc[5, "orig_txn_count_trailing_window"] == 1
    assert features.loc[5, "orig_total_amount_trailing_window"] == 300.0
    assert features.loc[5, "orig_steps_since_prev_txn"] == 25
    assert features.loc[5, "amount_to_orig_trailing_avg_amount"] == 1.0


def test_transfer_then_cashout_pattern_uses_configured_step_window() -> None:
    """A CASH_OUT is flagged when the same origin account recently transferred."""

    features = build_feature_set(
        _sample_paysim_frame(),
        {"C1": "E001"},
        window=3,
        transfer_cashout_window=2,
    )

    assert bool(features.loc[1, "is_transfer_then_cashout"]) is False
    assert bool(features.loc[2, "is_transfer_then_cashout"]) is True
    assert bool(features.loc[5, "is_transfer_then_cashout"]) is False


def test_load_paysim_accepts_csv_file_and_cleans_dtypes(tmp_path: Path) -> None:
    """CSV loading preserves identifiers and converts core fields to useful dtypes."""

    csv_path = tmp_path / "paysim.csv"
    _sample_paysim_frame().to_csv(csv_path, index=False)

    loaded = load_paysim(str(csv_path))

    assert str(loaded["type"].dtype) == "category"
    assert str(loaded["nameOrig"].dtype) == "string"
    assert loaded["step"].dtype == "int64"
    assert loaded["isFraud"].dtype == "int8"


def test_load_entity_mapping_parses_nested_json(tmp_path: Path) -> None:
    """Entity mapping loader extracts PaySim nameOrig join keys."""

    mapping_path = tmp_path / "entity_mapping.json"
    mapping_path.write_text(
        json.dumps(
            {
                "entities": [
                    {
                        "entity": {"entity_id": "E001"},
                        "source_ids": {"paysim": {"nameOrig": "C1"}},
                    },
                    {
                        "entity": {"entity_id": "E002"},
                        "source_ids": {"paysim": {"nameOrig": ["C2", "C3"]}},
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    assert load_entity_mapping(str(mapping_path)) == {
        "C1": "E001",
        "C2": "E002",
        "C3": "E002",
    }


def test_validate_entity_coverage_returns_counts_and_prints_summary(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Mapped entity coverage includes activity counts and missing-account warnings."""

    coverage = validate_entity_coverage(_sample_paysim_frame(), {"C1": "E001", "C4": "E004"})
    captured = capsys.readouterr()

    c1 = coverage[coverage["nameOrig"] == "C1"].iloc[0]
    c4 = coverage[coverage["nameOrig"] == "C4"].iloc[0]

    assert c1["total_txn_count"] == 4
    assert c1["transfer_txn_count"] == 1
    assert c1["cashout_txn_count"] == 2
    assert bool(c1["appears_as_nameOrig"]) is True
    assert c4["total_txn_count"] == 0
    assert bool(c4["appears_as_nameOrig"]) is False
    assert "PaySim mapped entity coverage:" in captured.out
    assert "WARNING: 1 mapped PaySim account(s) do not appear as nameOrig." in captured.out
