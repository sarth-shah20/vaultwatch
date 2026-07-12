# FinSpark Hackathon — Combined PS1 + PS2 Solution

**Bank of Maharashtra | FinSpark Hackathon | Deadline: July 16**

Unified system combining:
- **PS1**: Privileged Access Misuse & Insider Threat Detection
- **PS2**: AI-Driven Correlation of Cybersecurity Telemetry & Transactional Behaviour

Core thesis: intent/context-aware access risk (not just anomaly-based), correlated
across privileged-session behavior + transaction + security telemetry signals,
with quantum-safe crypto as a first-class concern (protect via PQC, prioritize via
crypto-inventory — not naive "quantum attack detection").

See `docs/ARCHITECTURE.md` for the full system design and `docs/FEATURES.md` for
the complete feature list mapped to problem-statement requirements.

## Repo layout

```
backend/                   FastAPI/Django backend (adjust to your stack)
  app/
    core/                  App config, DB session, settings
    api/                   Route handlers / endpoints
    shared/                Shared entity models, schemas used across PS1 & PS2
    ps1_insider_threat/
      baseline/            Behavioral baseline engine (per-entity: human + service accounts)
      risk_scoring/         Intent/context-aware risk scoring + risk-based access control
      pam/                  Privileged account inventory, session monitoring, PAM core
    ps2_correlation/
      fraud_detection/      Transaction fraud pattern models (PaySim-based)
      correlation_engine/   Joins PS1 signals + telemetry + transaction signals
      explainability/       Structured "why" generation for every alert/case
    quantum_module/
      crypto_inventory/     Data-flow + crypto-asset inventory, PQC migration priority scoring
      pqc_utils/            PQC encryption/signing helpers for credentials & audit logs
  tests/

ml/
  notebooks/               Exploration notebooks (CERT dataset, PaySim, feature engineering)
  data_pipeline/           Scripts to load/clean/join CERT + PaySim + synthetic telemetry
  models/                  Trained model artifacts
  evaluation/              Metrics, confusion matrices, ROC curves, SHAP outputs

data/
  raw/
    cert_insider_threat/   CMU CERT dataset (r4.2 or r6.2) — see docs/DATASETS.md
    paysim/                PaySim transaction dataset
  processed/               Cleaned/joined data ready for modeling
  synthetic/                Synthetic security telemetry generated to bridge CERT <-> PaySim

frontend/
  src/
    components/            Reusable UI components (alert cards, risk gauges, timelines)
    pages/                 Dashboard, incident view, crypto-inventory view
    services/              API client calls
    hooks/                 React hooks (data fetching, polling, websockets)

docs/                       Architecture notes, feature list, dataset notes, pitch outline
scripts/                    One-off utility scripts (data download, setup)
```

## Getting started

1. Read `docs/ARCHITECTURE.md` and `docs/FEATURES.md` first — everyone should agree
   on the shared entity model before writing code.
2. Download datasets — see `docs/DATASETS.md` for direct links and setup steps.
3. Each PS1/PS2/quantum module is designed to be built somewhat independently
   against the shared schemas in `backend/app/shared/` — agree on those schemas
   early (day 1) so no one blocks on anyone else.
