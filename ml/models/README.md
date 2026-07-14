# Trained fraud model artifacts

The trained PaySim fraud models are **committed directly** to this folder for team
handoff, so teammates can load and score without retraining:

| File | What it is |
|---|---|
| `fraud_model.json` | Full / primary demo model (raw balances included) — PR-AUC 0.9998 |
| `fraud_model_meta.json` | Full model metadata: feature list, tuned threshold, split, params |
| `fraud_model_hardened.json` | Production-realistic variant (raw + destination balances dropped) — PR-AUC 0.9195 |
| `fraud_model_hardened_meta.json` | Hardened model metadata |

See `ml/evaluation/fraud_report.md` for the side-by-side metrics and
`ml/evaluation/leakage_analysis.md` for why the two numbers differ.

## Loading a model

```python
from backend.app.ps2_correlation.fraud_detection import FraudScorer

# primary (default paths)
scorer = FraudScorer(root=".")
# hardened variant
hardened = FraudScorer(
    root=".",
    model_path="ml/models/fraud_model_hardened.json",
    meta_path="ml/models/fraud_model_hardened_meta.json",
)
```

The scorer is variant-agnostic — it reads the feature list and threshold from the
meta file you point it at.

## Regenerating (fallback)

Committed artifacts are the convenient default. To produce fresh weights (e.g. after
changing features), drop PaySim into `data/raw/paysim/` and run:

```bash
python3 ml/models/train_fraud_model.py --paysim-dir data/raw/paysim
```

Fixed random seeds make the results reproducible. Other `*.json` files written under
`ml/models/` remain gitignored; only these four artifacts are tracked.
