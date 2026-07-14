# PaySim Fraud Model — Evaluation Report

- Trained: 2026-07-14T11:37:36.525518+00:00
- Scope: TRANSFER + CASH_OUT (only types that carry fraud in PaySim)
- Split: time-based on step (train<= 323, val<= 377, test after)
- Two models are trained from the same split; see the artifact discussion in `leakage_analysis.md`.

## Model comparison (held-out test set)

| Model | Features | PR-AUC | ROC-AUC | Precision | Recall | F1 |
|---|---|---|---|---|---|---|
| full — primary demo model (raw balances included) | 18 | 0.9998 | 1.0000 | 0.996 | 0.986 | 0.991 |
| hardened — production-realistic variant (raw + destination balances dropped) | 14 | 0.9195 | 0.9975 | 0.963 | 0.815 | 0.883 |

## Per-model detail

### full — primary demo model (raw balances included)

- Test rows 408,077, fraud 4,010; threshold 0.9842; best_iteration 72.
- Confusion (tn, fp, fn, tp): 404053, 14, 57, 3953.
- Top SHAP features: error_balance_orig, oldbalanceOrg, newbalanceOrig, day_index, oldbalanceDest.

### hardened — production-realistic variant (raw + destination balances dropped)

- Test rows 408,077, fraud 4,010; threshold 0.9869; best_iteration 53.
- Confusion (tn, fp, fn, tp): 403943, 124, 743, 3267.
- Top SHAP features: error_balance_orig, day_index, hour_of_day, error_balance_dest, amount.

## Reading these numbers

PR-AUC is the headline metric because the positive rate is ~0.3% (accuracy is uninformative). The **full** model is near-perfect largely because of PaySim balance-column artifacts (see `leakage_analysis.md`); the **hardened** model drops the raw + destination balances for a lower, more real-world-representative score. Note the hardened variant keeps `error_balance_dest`, which still partially reflects the destination-balance quirk — a strict behavioral-only floor (no balance-derived features) is far lower still (~0.34 PR-AUC).
