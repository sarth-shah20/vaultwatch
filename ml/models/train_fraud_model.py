"""Train an explainable XGBoost fraud model on PaySim (TRANSFER + CASH_OUT).

Pipeline
--------
1. Load PaySim and keep only TRANSFER + CASH_OUT (the only transaction types that
   ever carry fraud in PaySim); other types score ~0 by construction.
2. Build transaction-level features via ml.data_pipeline.paysim_features.
3. Time-based holdout split on `step` (train earliest ~70%, validation ~15%,
   test last ~15%) — realistic and leakage-free.
4. Train XGBoost with scale_pos_weight for the ~0.3% positive rate and early
   stopping on validation PR-AUC.
5. Tune the decision threshold on validation (max F1).
6. Evaluate on the untouched test set: PR-AUC, ROC-AUC, precision/recall/F1,
   confusion matrix. Persist model + metadata + a metrics report + SHAP importances.

Run: python3 ml/models/train_fraud_model.py [--paysim-dir data/raw/paysim]
"""
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.metrics import (
    average_precision_score,
    confusion_matrix,
    precision_recall_curve,
    precision_recall_fscore_support,
    roc_auc_score,
)

from ml.data_pipeline.paysim_features import build_feature_set, load_paysim

# Transaction-level features only. Deliberately EXCLUDES leakage/identifier columns:
# isFraud (label), isFlaggedFraud (PaySim's own post-hoc flag), step (split key),
# raw nameOrig/nameDest, entity_id.
FEATURE_COLUMNS = [
    "amount",
    "oldbalanceOrg",
    "newbalanceOrig",
    "oldbalanceDest",
    "newbalanceDest",
    "error_balance_orig",
    "error_balance_dest",
    "is_merchant_dest",
    "hour_of_day",
    "day_index",
    "orig_txn_count_trailing_window",
    "orig_total_amount_trailing_window",
    "orig_unique_dest_trailing_window",
    "orig_steps_since_prev_txn",
    "amount_to_orig_trailing_avg_amount",
    "is_transfer_then_cashout",
    "type_CASH_OUT",
    "type_TRANSFER",
]
LABEL = "isFraud"
FRAUD_ELIGIBLE_TYPES = ("TRANSFER", "CASH_OUT")

DEFAULT_PAYSIM_DIR = "data/raw/paysim"
MODEL_PATH = "ml/models/fraud_model.json"
META_PATH = "ml/models/fraud_model_meta.json"
METRICS_PATH = "ml/evaluation/fraud_metrics.json"
REPORT_PATH = "ml/evaluation/fraud_report.md"

XGB_PARAMS = dict(
    n_estimators=600,
    max_depth=6,
    learning_rate=0.1,
    subsample=0.8,
    colsample_bytree=0.8,
    min_child_weight=1.0,
    reg_lambda=1.0,
    objective="binary:logistic",
    eval_metric="aucpr",
    tree_method="hist",
    random_state=42,
    n_jobs=-1,
)


def build_matrix(paysim_dir: str) -> pd.DataFrame:
    """Load PaySim, restrict to fraud-eligible types, and build the feature frame."""

    df = load_paysim(paysim_dir)
    df = df[df["type"].astype("string").isin(FRAUD_ELIGIBLE_TYPES)].copy()
    feats = build_feature_set(df, entity_map={})
    for col in ("is_merchant_dest", "is_transfer_then_cashout"):
        feats[col] = feats[col].astype("int8")
    for col in ("type_CASH_OUT", "type_TRANSFER"):
        if col not in feats.columns:
            feats[col] = np.int8(0)
    return feats.reset_index(drop=True)


def time_split(feats: pd.DataFrame, train_frac: float = 0.70, val_frac: float = 0.15):
    """Split by `step` so no step straddles two splits (leakage-free, temporal)."""

    steps_sorted = feats["step"].sort_values(kind="mergesort").to_numpy()
    n = len(steps_sorted)
    train_cut = int(steps_sorted[int(train_frac * n)])
    val_cut = int(steps_sorted[int((train_frac + val_frac) * n)])
    if val_cut <= train_cut:
        val_cut = train_cut + 1

    train = feats[feats["step"] <= train_cut]
    val = feats[(feats["step"] > train_cut) & (feats["step"] <= val_cut)]
    test = feats[feats["step"] > val_cut]
    for name, part in (("train", train), ("val", val), ("test", test)):
        if part.empty or part[LABEL].sum() == 0:
            raise ValueError(f"Split '{name}' is empty or has no fraud positives; adjust fractions.")
    return train, val, test, train_cut, val_cut


def best_f1_threshold(y_true: np.ndarray, proba: np.ndarray) -> float:
    """Threshold that maximizes F1 on the validation set."""

    precision, recall, thresholds = precision_recall_curve(y_true, proba)
    if len(thresholds) == 0:
        return 0.5
    f1 = 2 * precision[:-1] * recall[:-1] / (precision[:-1] + recall[:-1] + 1e-12)
    return float(thresholds[int(np.nanargmax(f1))])


def train_model(train: pd.DataFrame, val: pd.DataFrame) -> xgb.XGBClassifier:
    x_train, y_train = train[FEATURE_COLUMNS], train[LABEL].to_numpy()
    x_val, y_val = val[FEATURE_COLUMNS], val[LABEL].to_numpy()
    pos = max(int(y_train.sum()), 1)
    neg = int((y_train == 0).sum())
    model = xgb.XGBClassifier(
        scale_pos_weight=neg / pos,
        early_stopping_rounds=40,
        **XGB_PARAMS,
    )
    model.fit(x_train, y_train, eval_set=[(x_val, y_val)], verbose=False)
    return model


def evaluate(model: xgb.XGBClassifier, part: pd.DataFrame, threshold: float) -> dict:
    proba = model.predict_proba(part[FEATURE_COLUMNS])[:, 1]
    y_true = part[LABEL].to_numpy()
    y_pred = (proba >= threshold).astype(int)
    precision, recall, f1, _ = precision_recall_fscore_support(
        y_true, y_pred, average="binary", zero_division=0
    )
    tn, fp, fn, tp = confusion_matrix(y_true, y_pred, labels=[0, 1]).ravel()
    return {
        "rows": int(len(part)),
        "fraud": int(y_true.sum()),
        "pr_auc": float(average_precision_score(y_true, proba)),
        "roc_auc": float(roc_auc_score(y_true, proba)),
        "precision": float(precision),
        "recall": float(recall),
        "f1": float(f1),
        "confusion_matrix": {"tn": int(tn), "fp": int(fp), "fn": int(fn), "tp": int(tp)},
    }


def shap_importance(model: xgb.XGBClassifier, x: pd.DataFrame, sample: int = 3000) -> list[dict]:
    import shap

    subset = x.sample(min(sample, len(x)), random_state=42)
    values = shap.TreeExplainer(model).shap_values(subset)
    mean_abs = np.abs(values).mean(axis=0)
    ranked = sorted(zip(FEATURE_COLUMNS, mean_abs), key=lambda kv: -kv[1])
    return [{"feature": f, "mean_abs_shap": float(v)} for f, v in ranked]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--paysim-dir", default=DEFAULT_PAYSIM_DIR)
    parser.add_argument("--root", default=".", help="repo root for output paths")
    args = parser.parse_args()
    root = Path(args.root).resolve()

    start = time.time()
    print("Building feature matrix (TRANSFER + CASH_OUT only) ...")
    feats = build_matrix(args.paysim_dir)
    print(f"  {len(feats):,} rows, {int(feats[LABEL].sum()):,} fraud "
          f"({100 * feats[LABEL].mean():.3f}%)")

    train, val, test, train_cut, val_cut = time_split(feats)
    print(f"Time split by step: train<= {train_cut} ({len(train):,}), "
          f"val<= {val_cut} ({len(val):,}), test> {val_cut} ({len(test):,})")

    print("Training XGBoost ...")
    model = train_model(train, val)
    threshold = best_f1_threshold(val[LABEL].to_numpy(), model.predict_proba(val[FEATURE_COLUMNS])[:, 1])
    print(f"  best_iteration={model.best_iteration}  tuned_threshold={threshold:.4f}")

    metrics = {"validation": evaluate(model, val, threshold), "test": evaluate(model, test, threshold)}
    importance = shap_importance(model, test[FEATURE_COLUMNS])

    # Persist artifacts.
    (root / "ml/models").mkdir(parents=True, exist_ok=True)
    (root / "ml/evaluation").mkdir(parents=True, exist_ok=True)
    model.save_model(str(root / MODEL_PATH))
    meta = {
        "model_path": MODEL_PATH,
        "features": FEATURE_COLUMNS,
        "label": LABEL,
        "scope": "TRANSFER+CASH_OUT",
        "threshold": threshold,
        "best_iteration": int(model.best_iteration),
        "scale_pos_weight": float(model.get_params()["scale_pos_weight"]),
        "split": {"train_max_step": train_cut, "val_max_step": val_cut, "strategy": "time_based"},
        "xgb_params": XGB_PARAMS,
        "trained_at": datetime.now(timezone.utc).isoformat(),
    }
    (root / META_PATH).write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    (root / METRICS_PATH).write_text(
        json.dumps({"metrics": metrics, "shap_importance": importance, "meta": meta}, indent=2) + "\n",
        encoding="utf-8",
    )
    _write_report(root / REPORT_PATH, meta, metrics, importance)

    took = time.time() - start
    t = metrics["test"]
    print(f"\nTEST: PR-AUC={t['pr_auc']:.4f}  ROC-AUC={t['roc_auc']:.4f}  "
          f"precision={t['precision']:.3f}  recall={t['recall']:.3f}  F1={t['f1']:.3f}")
    print(f"  confusion: {t['confusion_matrix']}")
    print(f"Top features: {[i['feature'] for i in importance[:5]]}")
    print(f"Saved model -> {MODEL_PATH}; report -> {REPORT_PATH}. Done in {took:.1f}s.")


def _write_report(path: Path, meta: dict, metrics: dict, importance: list[dict]) -> None:
    t, v = metrics["test"], metrics["validation"]
    lines = [
        "# PaySim Fraud Model — Evaluation Report",
        "",
        f"- Trained: {meta['trained_at']}",
        f"- Scope: {meta['scope']} (only types that carry fraud in PaySim)",
        f"- Split: time-based on step (train<= {meta['split']['train_max_step']}, "
        f"val<= {meta['split']['val_max_step']}, test after)",
        f"- Model: XGBoost, best_iteration={meta['best_iteration']}, "
        f"scale_pos_weight={meta['scale_pos_weight']:.1f}, tuned threshold={meta['threshold']:.4f}",
        "",
        "## Test set (held out, untouched during training)",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Rows | {t['rows']:,} |",
        f"| Fraud (positives) | {t['fraud']:,} |",
        f"| PR-AUC (avg precision) | {t['pr_auc']:.4f} |",
        f"| ROC-AUC | {t['roc_auc']:.4f} |",
        f"| Precision @ threshold | {t['precision']:.3f} |",
        f"| Recall @ threshold | {t['recall']:.3f} |",
        f"| F1 @ threshold | {t['f1']:.3f} |",
        f"| Confusion (tn, fp, fn, tp) | {t['confusion_matrix']['tn']}, {t['confusion_matrix']['fp']}, "
        f"{t['confusion_matrix']['fn']}, {t['confusion_matrix']['tp']} |",
        "",
        f"Validation PR-AUC {v['pr_auc']:.4f} / ROC-AUC {v['roc_auc']:.4f}.",
        "",
        "## Top features (mean |SHAP|)",
        "",
        "| Rank | Feature | mean|SHAP| |",
        "|---|---|---|",
    ]
    for rank, item in enumerate(importance[:10], start=1):
        lines.append(f"| {rank} | {item['feature']} | {item['mean_abs_shap']:.4f} |")
    lines += [
        "",
        "PR-AUC is the headline metric because the positive rate is ~0.3% (accuracy is "
        "uninformative). PaySim is a comparatively easy dataset; the value of this module for "
        "PS2 is the explainable per-transaction reasons it feeds into the correlation engine.",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
