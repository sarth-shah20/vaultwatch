# PaySim Fraud Model — Evaluation Report

- Trained: 2026-07-14T10:24:04.403470+00:00
- Scope: TRANSFER+CASH_OUT (only types that carry fraud in PaySim)
- Split: time-based on step (train<= 323, val<= 377, test after)
- Model: XGBoost, best_iteration=72, scale_pos_weight=534.8, tuned threshold=0.9842

## Test set (held out, untouched during training)

| Metric | Value |
|---|---|
| Rows | 408,077 |
| Fraud (positives) | 4,010 |
| PR-AUC (avg precision) | 0.9998 |
| ROC-AUC | 1.0000 |
| Precision @ threshold | 0.996 |
| Recall @ threshold | 0.986 |
| F1 @ threshold | 0.991 |
| Confusion (tn, fp, fn, tp) | 404053, 14, 57, 3953 |

Validation PR-AUC 0.9992 / ROC-AUC 1.0000.

## Top features (mean |SHAP|)

| Rank | Feature | mean|SHAP| |
|---|---|---|
| 1 | error_balance_orig | 4.3414 |
| 2 | oldbalanceOrg | 0.8928 |
| 3 | newbalanceOrig | 0.8668 |
| 4 | day_index | 0.8141 |
| 5 | oldbalanceDest | 0.4384 |
| 6 | amount | 0.2675 |
| 7 | newbalanceDest | 0.2347 |
| 8 | orig_total_amount_trailing_window | 0.1985 |
| 9 | hour_of_day | 0.1683 |
| 10 | error_balance_dest | 0.1205 |

PR-AUC is the headline metric because the positive rate is ~0.3% (accuracy is uninformative). PaySim is a comparatively easy dataset; the value of this module for PS2 is the explainable per-transaction reasons it feeds into the correlation engine.
