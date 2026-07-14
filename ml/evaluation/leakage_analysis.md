# Fraud Model — Leakage & Artifact Analysis

Why does the PaySim fraud model score PR-AUC ~1.0? Is it leakage? Short answer:
**not label leakage, but the near-perfect score is driven by PaySim simulation
artifacts in the balance columns and must not be read as real-world performance.**

## What the model actually consumes

The raw balance columns (`oldbalanceOrg`, `newbalanceOrig`, `oldbalanceDest`,
`newbalanceDest`) **are fed directly** into the model, alongside the derived
`error_balance_*` features. The SHAP report is not mislabeling them. What is
**excluded** (genuine leakage guards): `isFraud` (label), `isFlaggedFraud`
(PaySim's own post-hoc flag), `step` (split key), raw account IDs, `entity_id`.

None of the inputs are the label or derived from it, so this is **not label
leakage**. The concern is subtler: some balance patterns are *simulation
artifacts* that correlate with fraud only because of how PaySim was generated.

## PaySim artifact check (full TRANSFER+CASH_OUT set)

| Pattern | Fraud rows | Non-fraud rows |
|---|---|---|
| `oldbalanceOrg == amount` (account fully drained) | **97.8%** | **0.0%** |
| destination balances both `== 0` | **49.6%** | **0.1%** |
| `newbalanceOrig == 0` | 98.1% | 90.1% |

`oldbalanceOrg == amount` is an almost perfect fraud signature, and dest-balances
being zero for fraud is a well-documented PaySim quirk (destination balances are
not updated for fraudulent transactions in the simulation). In production these
would not hold so cleanly, which is why the headline metric is optimistic.

## Ablation (held-out test set)

| Feature set | PR-AUC | ROC-AUC |
|---|---|---|
| Full (baseline) | 0.9996 | 1.0000 |
| No destination balances | 0.9993 | 0.9998 |
| No raw balances (keep `error_*`) | 0.9074 | 0.9969 |
| Behavioral only (no balances at all) | **0.3375** | 0.8590 |

Removing all balance information collapses PR-AUC from ~1.0 to 0.34 — the fraud
signal lives almost entirely in the balance columns. Dropping destination
balances barely moves the score; the origin-side full-drain signature dominates.

## Conclusion & guidance

- The ROC-AUC of 1.0 is **legitimate on this dataset** (no future/label info is
  used) but reflects PaySim's near-deterministic, artifact-heavy fraud pattern —
  **not** expected real-world fraud-detection accuracy.
- For the demo, the honest framing is: the model is accurate *and explainable*
  (every score ships with SHAP reasons), and its real PS2 value is feeding
  explainable per-transaction signals into the correlation engine — not the
  headline number.
- If a more production-realistic model is wanted, drop the raw/destination
  balances and lean on behavioral + `error_*` ratio features (expect a much
  lower, more honest PR-AUC). Kept as an option, not the default.
