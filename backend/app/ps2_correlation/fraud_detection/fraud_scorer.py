"""Explainable fraud scoring for PS2.

Loads the trained XGBoost model and turns a transaction's features into a shared
``RiskAssessment`` whose ``reasons`` come straight from that transaction's SHAP
contributions (top drivers, rendered in plain English). This is the PS2
"explainable AI-driven threat intelligence" requirement — every score ships with
its structured "why" from the moment it is created, ready for the correlation
engine and the incident case file.

Usage:
    scorer = FraudScorer(root="/path/to/repo")
    assessment = scorer.score_row(feature_row, entity_id="E027")

``feature_row`` is a mapping/Series holding the model feature columns as produced
by ml.data_pipeline.paysim_features.build_feature_set.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, Mapping

import numpy as np
import pandas as pd
import xgboost as xgb

from backend.app.shared.entities import Reason, RiskAssessment

DOMAIN = "ps2_transaction"
DEFAULT_MODEL_PATH = "ml/models/fraud_model.json"
DEFAULT_META_PATH = "ml/models/fraud_model_meta.json"

# Plain-English phrasing for each model feature, used to render reasons.
FEATURE_PHRASES: dict[str, str] = {
    "amount": "transaction amount",
    "oldbalanceOrg": "origin balance before the transaction",
    "newbalanceOrig": "origin balance after the transaction",
    "oldbalanceDest": "destination balance before the transaction",
    "newbalanceDest": "destination balance after the transaction",
    "error_balance_orig": "origin balance does not reconcile after the transaction",
    "error_balance_dest": "destination balance does not reconcile after the transaction",
    "is_merchant_dest": "destination is a merchant account",
    "hour_of_day": "hour of day",
    "day_index": "day index",
    "orig_txn_count_trailing_window": "origin transaction count in the trailing window",
    "orig_total_amount_trailing_window": "origin total amount in the trailing window",
    "orig_unique_dest_trailing_window": "distinct destinations in the trailing window",
    "orig_steps_since_prev_txn": "time since the origin's previous transaction",
    "amount_to_orig_trailing_avg_amount": "amount vs. the origin's recent average",
    "is_transfer_then_cashout": "a transfer was immediately followed by a cash-out",
    "type_CASH_OUT": "transaction type is CASH_OUT",
    "type_TRANSFER": "transaction type is TRANSFER",
}


class FraudScorer:
    """Loads the trained model + SHAP explainer and scores transactions."""

    def __init__(
        self,
        root: str | Path = ".",
        model_path: str = DEFAULT_MODEL_PATH,
        meta_path: str = DEFAULT_META_PATH,
    ) -> None:
        root = Path(root)
        meta = json.loads((root / meta_path).read_text(encoding="utf-8"))
        self.features: list[str] = list(meta["features"])
        self.threshold: float = float(meta.get("threshold", 0.5))

        self._booster = xgb.Booster()
        self._booster.load_model(str(root / model_path))
        self._booster.set_param({"nthread": 1})

        # TreeExplainer is exact and fast for tree models; created once and reused.
        import shap

        self._explainer = shap.TreeExplainer(self._booster)

    def _frame(self, row: Mapping) -> pd.DataFrame:
        values = {}
        for feature in self.features:
            value = row[feature] if feature in row else np.nan
            if isinstance(value, (bool, np.bool_)):
                value = int(value)
            values[feature] = pd.to_numeric(pd.Series([value]), errors="coerce")
        return pd.DataFrame(values, columns=self.features)

    def predict_proba(self, row: Mapping) -> float:
        matrix = xgb.DMatrix(self._frame(row), feature_names=self.features)
        return float(self._booster.predict(matrix)[0])

    def score_row(
        self,
        row: Mapping,
        entity_id: str | None = None,
        top_k: int = 3,
    ) -> RiskAssessment:
        """Return a RiskAssessment with SHAP-derived, plain-English reasons."""

        frame = self._frame(row)
        proba = float(self._booster.predict(xgb.DMatrix(frame, feature_names=self.features))[0])

        contributions = np.asarray(self._explainer.shap_values(frame))
        if contributions.ndim == 2:
            contributions = contributions[0]
        reasons = self._reasons(frame.iloc[0], contributions, top_k)

        resolved_id = entity_id or str(row.get("entity_id") if hasattr(row, "get") else None) or "unknown"
        return RiskAssessment(entity_id=resolved_id, score=proba, reasons=reasons)

    def score_frame(self, feature_frame: pd.DataFrame, top_k: int = 3) -> list[RiskAssessment]:
        return [
            self.score_row(record, entity_id=record.get("entity_id"), top_k=top_k)
            for record in feature_frame.to_dict(orient="records")
        ]

    def _reasons(self, values: pd.Series, contributions: np.ndarray, top_k: int) -> list[Reason]:
        abs_total = float(np.abs(contributions).sum()) + 1e-12
        order = np.argsort(-np.abs(contributions))
        reasons: list[Reason] = []
        for idx in order[:top_k]:
            feature = self.features[idx]
            signed = float(contributions[idx])
            if signed == 0.0:
                continue
            direction = "raises" if signed > 0 else "lowers"
            raw_value = values[feature]
            raw_txt = "n/a" if pd.isna(raw_value) else f"{float(raw_value):g}"
            phrase = FEATURE_PHRASES.get(feature, feature)
            reasons.append(
                Reason(
                    signal_name=feature,
                    domain=DOMAIN,
                    weight=round(abs(signed) / abs_total, 4),
                    raw_value=f"{phrase} ({feature}={raw_txt}); {direction} fraud risk",
                )
            )
        return reasons


def score_transactions(
    feature_frame: pd.DataFrame,
    root: str | Path = ".",
    top_k: int = 3,
) -> list[RiskAssessment]:
    """Convenience wrapper: load the scorer once and score a feature frame."""

    return FraudScorer(root=root).score_frame(feature_frame, top_k=top_k)
