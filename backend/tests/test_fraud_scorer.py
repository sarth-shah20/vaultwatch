"""Tests for the explainable fraud scorer (trains a tiny model in a fixture)."""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest
import xgboost as xgb

from backend.app.ps2_correlation.fraud_detection import DOMAIN, FraudScorer
from backend.app.shared.entities import Reason, RiskAssessment
from ml.models.train_fraud_model import FEATURE_COLUMNS


@pytest.fixture
def scorer_root(tmp_path):
    """Train a small, separable model over the real feature columns and save it."""

    rng = np.random.default_rng(0)
    n = 800
    x = pd.DataFrame({feature: rng.normal(size=n) for feature in FEATURE_COLUMNS})
    y = ((x["error_balance_orig"] > 0.3) | (x["is_transfer_then_cashout"] > 0.5)).astype(int)

    model = xgb.XGBClassifier(
        n_estimators=40, max_depth=3, eval_metric="logloss", random_state=0, n_jobs=1
    )
    model.fit(x, y)

    (tmp_path / "ml/models").mkdir(parents=True)
    model.save_model(str(tmp_path / "ml/models/fraud_model.json"))
    (tmp_path / "ml/models/fraud_model_meta.json").write_text(
        json.dumps({"features": FEATURE_COLUMNS, "threshold": 0.5}), encoding="utf-8"
    )
    return tmp_path


def _row(**overrides) -> dict:
    row = {feature: 0.0 for feature in FEATURE_COLUMNS}
    row["type_TRANSFER"] = 1  # fraud-eligible by default so the scorer will score it
    row.update(overrides)
    return row


def test_score_row_returns_explained_risk_assessment(scorer_root) -> None:
    scorer = FraudScorer(root=scorer_root)
    row = _row(error_balance_orig=5.0, is_transfer_then_cashout=1, type_TRANSFER=1)

    assessment = scorer.score_row(row, entity_id="E027", top_k=3)

    assert isinstance(assessment, RiskAssessment)
    assert assessment.entity_id == "E027"
    assert 0.0 <= assessment.score <= 1.0
    assert 1 <= len(assessment.reasons) <= 3
    for reason in assessment.reasons:
        assert isinstance(reason, Reason)
        assert reason.domain == DOMAIN
        assert 0.0 <= reason.weight <= 1.0
        assert reason.signal_name in FEATURE_COLUMNS
        assert reason.raw_value  # human-readable evidence attached


def test_higher_balance_error_scores_higher_and_reads_entity_from_column(scorer_root) -> None:
    scorer = FraudScorer(root=scorer_root)
    frame = pd.DataFrame(
        [
            _row(entity_id="E010"),
            _row(entity_id="E027", error_balance_orig=9.0, is_transfer_then_cashout=1),
        ]
    )

    assessments = scorer.score_frame(frame)

    assert [a.entity_id for a in assessments] == ["E010", "E027"]
    assert assessments[1].score >= assessments[0].score


def test_missing_features_do_not_crash(scorer_root) -> None:
    scorer = FraudScorer(root=scorer_root)
    # Only a couple of features present; the rest should be treated as missing (NaN).
    assessment = scorer.score_row({"amount": 1000.0, "type_CASH_OUT": 1}, entity_id="E001")
    assert isinstance(assessment, RiskAssessment)
    assert 0.0 <= assessment.score <= 1.0


def test_ineligible_transaction_types_return_none(scorer_root) -> None:
    scorer = FraudScorer(root=scorer_root)

    # Non-fraud-eligible types identified by the raw `type` column.
    for txn_type in ("PAYMENT", "CASH_IN", "DEBIT"):
        row = {feature: 0.0 for feature in FEATURE_COLUMNS}
        row["type"] = txn_type
        assert scorer.score_row(row, entity_id="E010") is None

    # No raw type and neither one-hot set -> also ineligible.
    all_zero = {feature: 0.0 for feature in FEATURE_COLUMNS}
    assert scorer.score_row(all_zero, entity_id="E010") is None


def test_score_frame_skips_ineligible_rows(scorer_root) -> None:
    scorer = FraudScorer(root=scorer_root)
    base = {feature: 0.0 for feature in FEATURE_COLUMNS}
    frame = pd.DataFrame(
        [
            {**base, "type": "TRANSFER", "type_TRANSFER": 1, "error_balance_orig": 9.0, "entity_id": "E027"},
            {**base, "type": "PAYMENT", "entity_id": "E010"},  # ineligible -> skipped
            {**base, "type": "CASH_OUT", "type_CASH_OUT": 1, "entity_id": "E011"},
        ]
    )

    assessments = scorer.score_frame(frame)

    assert len(assessments) == 2
    assert {a.entity_id for a in assessments} == {"E027", "E011"}

def test_score_row_derives_global_synthetic_event_time_from_step(scorer_root) -> None:
    scorer = FraudScorer(root=scorer_root)
    assessment = scorer.score_row(_row(step=13), entity_id="E027")
    assert assessment is not None
    assert assessment.event_time is not None
    assert assessment.event_time.isoformat() == "2010-01-01T13:00:00+00:00"
    assert assessment.time_basis == "synthetic_step_mapping"
    assert assessment.domain == DOMAIN
    assert assessment.source == "paysim"
