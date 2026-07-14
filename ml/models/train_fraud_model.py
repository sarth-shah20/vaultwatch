"""Train explainable XGBoost fraud models on PaySim (TRANSFER + CASH_OUT).

Trains TWO models from the same features/split so the pitch can contrast them:

1. **full (primary demo model)** — includes the raw balance columns. Near-perfect
   on PaySim, but that score leans on simulation artifacts (see
   ml/evaluation/leakage_analysis.md). This is the headline demo model.
2. **hardened (production-realistic variant)** — drops the raw + destination
   balance columns, keeping balance-consistency (error_*) and behavioral
   features. Lower but far more representative of real-world fraud detection.

Pipeline (shared by both): load PaySim -> keep TRANSFER + CASH_OUT -> build
transaction-level features -> time-based holdout split on `step` -> XGBoost with
scale_pos_weight + early stopping -> validation-tuned threshold -> evaluate on the
untouched test set (PR-AUC, ROC-AUC, precision/recall/F1) + SHAP importances.

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

# Raw balance columns — near-deterministic fraud signatures in PaySim (a synthetic
# artifact). Present in the full model, dropped in the hardened variant.
RAW_BALANCE_COLUMNS = ["oldbalanceOrg", "newbalanceOrig", "oldbalanceDest", "newbalanceDest"]

# Transaction-level features. Deliberately EXCLUDES leakage/identifier columns:
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
# Hardened: drop the raw balance columns, keep error_* consistency + behavioral.
HARDENED_FEATURE_COLUMNS = [c for c in FEATURE_COLUMNS if c not in RAW_BALANCE_COLUMNS]

LABEL = "isFraud"
FRAUD_ELIGIBLE_TYPES = ("TRANSFER", "CASH_OUT")

DEFAULT_PAYSIM_DIR = "data/raw/paysim"
METRICS_PATH = "ml/evaluation/fraud_metrics.json"
REPORT_PATH = "ml/evaluation/fraud_report.md"

VARIANTS = [
    {
        "name": "full",
        "label": "primary demo model (raw balances included)",
        "features": FEATURE_COLUMNS,
        "model_path": "ml/models/fraud_model.json",
        "meta_path": "ml/models/fraud_model_meta.json",
    },
    {
        "name": "hardened",
        "label": "production-realistic variant (raw + destination balances dropped)",
        "features": HARDENED_FEATURE_COLUMNS,
        "model_path": "ml/models/fraud_model_hardened.json",
        "meta_path": "ml/models/fraud_model_hardened_meta.json",
    },
]

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


def train_model(train: pd.DataFrame, val: pd.DataFrame, features: list[str]) -> xgb.XGBClassifier:
    y_train = train[LABEL].to_numpy()
    pos = max(int(y_train.sum()), 1)
    neg = int((y_train == 0).sum())
    model = xgb.XGBClassifier(
        scale_pos_weight=neg / pos,
        early_stopping_rounds=40,
        **XGB_PARAMS,
    )
    model.fit(
        train[features], y_train,
        eval_set=[(val[features], val[LABEL].to_numpy())],
        verbose=False,
    )
    return model


def evaluate(model: xgb.XGBClassifier, part: pd.DataFrame, features: list[str], threshold: float) -> dict:
    proba = model.predict_proba(part[features])[:, 1]
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


def shap_importance(model: xgb.XGBClassifier, x: pd.DataFrame, features: list[str], sample: int = 3000) -> list[dict]:
    import shap

    subset = x.sample(min(sample, len(x)), random_state=42)
    values = shap.TreeExplainer(model).shap_values(subset)
    mean_abs = np.abs(values).mean(axis=0)
    ranked = sorted(zip(features, mean_abs), key=lambda kv: -kv[1])
    return [{"feature": f, "mean_abs_shap": float(v)} for f, v in ranked]


def train_variant(variant: dict, train, val, test, split_meta: dict, root: Path) -> dict:
    features = variant["features"]
    print(f"\n== variant: {variant['name']} ({len(features)} features) ==")
    model = train_model(train, val, features)
    threshold = best_f1_threshold(val[LABEL].to_numpy(), model.predict_proba(val[features])[:, 1])
    metrics = {
        "validation": evaluate(model, val, features, threshold),
        "test": evaluate(model, test, features, threshold),
    }
    importance = shap_importance(model, test[features], features)

    model.save_model(str(root / variant["model_path"]))
    meta = {
        "variant": variant["name"],
        "label": variant["label"],
        "model_path": variant["model_path"],
        "features": features,
        "label_column": LABEL,
        "scope": "TRANSFER+CASH_OUT",
        "threshold": threshold,
        "best_iteration": int(model.best_iteration),
        "scale_pos_weight": float(model.get_params()["scale_pos_weight"]),
        "split": split_meta,
        "xgb_params": XGB_PARAMS,
        "trained_at": datetime.now(timezone.utc).isoformat(),
    }
    (root / variant["meta_path"]).write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")

    t = metrics["test"]
    print(f"  TEST PR-AUC={t['pr_auc']:.4f} ROC-AUC={t['roc_auc']:.4f} "
          f"precision={t['precision']:.3f} recall={t['recall']:.3f} F1={t['f1']:.3f}")
    print(f"  top features: {[i['feature'] for i in importance[:5]]}")
    return {"meta": meta, "metrics": metrics, "shap_importance": importance}


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
    split_meta = {"train_max_step": train_cut, "val_max_step": val_cut, "strategy": "time_based"}
    print(f"Time split by step: train<= {train_cut} ({len(train):,}), "
          f"val<= {val_cut} ({len(val):,}), test> {val_cut} ({len(test):,})")

    (root / "ml/models").mkdir(parents=True, exist_ok=True)
    (root / "ml/evaluation").mkdir(parents=True, exist_ok=True)

    results = {v["name"]: train_variant(v, train, val, test, split_meta, root) for v in VARIANTS}

    (root / METRICS_PATH).write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    _write_report(root / REPORT_PATH, results)

    print(f"\nSaved models + report. Done in {time.time() - start:.1f}s.")
    for name, res in results.items():
        print(f"  {name:9s} test PR-AUC={res['metrics']['test']['pr_auc']:.4f}")


def _write_report(path: Path, results: dict) -> None:
    first = next(iter(results.values()))
    split = first["meta"]["split"]
    lines = [
        "# PaySim Fraud Model — Evaluation Report",
        "",
        f"- Trained: {first['meta']['trained_at']}",
        "- Scope: TRANSFER + CASH_OUT (only types that carry fraud in PaySim)",
        f"- Split: time-based on step (train<= {split['train_max_step']}, "
        f"val<= {split['val_max_step']}, test after)",
        "- Two models are trained from the same split; see the artifact discussion in "
        "`leakage_analysis.md`.",
        "",
        "## Model comparison (held-out test set)",
        "",
        "| Model | Features | PR-AUC | ROC-AUC | Precision | Recall | F1 |",
        "|---|---|---|---|---|---|---|",
    ]
    for name, res in results.items():
        m, meta = res["metrics"]["test"], res["meta"]
        lines.append(
            f"| {name} — {meta['label']} | {len(meta['features'])} | {m['pr_auc']:.4f} | "
            f"{m['roc_auc']:.4f} | {m['precision']:.3f} | {m['recall']:.3f} | {m['f1']:.3f} |"
        )
    lines += ["", "## Per-model detail", ""]
    for name, res in results.items():
        m, meta = res["metrics"]["test"], res["meta"]
        cm = m["confusion_matrix"]
        lines += [
            f"### {name} — {meta['label']}",
            "",
            f"- Test rows {m['rows']:,}, fraud {m['fraud']:,}; threshold {meta['threshold']:.4f}; "
            f"best_iteration {meta['best_iteration']}.",
            f"- Confusion (tn, fp, fn, tp): {cm['tn']}, {cm['fp']}, {cm['fn']}, {cm['tp']}.",
            f"- Top SHAP features: {', '.join(i['feature'] for i in res['shap_importance'][:5])}.",
            "",
        ]
    lines += [
        "## Reading these numbers",
        "",
        "PR-AUC is the headline metric because the positive rate is ~0.3% (accuracy is "
        "uninformative). The **full** model is near-perfect largely because of PaySim balance-column "
        "artifacts (see `leakage_analysis.md`); the **hardened** model drops the raw + destination "
        "balances for a lower, more real-world-representative score. Note the hardened variant keeps "
        "`error_balance_dest`, which still partially reflects the destination-balance quirk — a strict "
        "behavioral-only floor (no balance-derived features) is far lower still (~0.34 PR-AUC).",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
