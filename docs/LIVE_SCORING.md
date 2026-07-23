# Live In-Process Scoring

## What changed

Before this: `POST /assessments` accepted **already-scored** `RiskAssessment`
objects. The actual model inference ran in a separate offline process
(`ml/replay_cert_assessments.py` for CERT; the offline ml pipeline for PaySim),
which then POSTed finished verdicts to the API. The API's live capability was
**correlation**, not **detection** — an external script detected, the server
only fused.

Now: `POST /ingest/transaction` and `POST /ingest/behavioral` run the existing,
already-trained models **in-process, on request**. The server itself scores an
unscored input and feeds the result through the same
`AssessmentIngestionService` used by `/assessments` — identical validation,
temporal correlation, and incident upsert, unchanged.

## The honest boundary (read before extending this)

**Live = model inference + correlation + incident.** Push a prepared feature
row/window, the server scores it, correlates it, and decides access — in one
process, no precomputed verdict.

**Still offline, still batch:** raw log/CSV parsing into feature rows.
- CERT: `ml/data_pipeline/cert_behavioral_windows.py` builds user-hour windows
  from 30-day rolling per-user/role-peer baselines. This is genuinely stateful,
  multi-day-history work — it is not reproduced live. `POST /ingest/behavioral`
  takes a **prepared window** (the same shape the offline pipeline produces),
  not a raw logon/device/file/email row.
- PaySim: `ml/data_pipeline/paysim_features.py` builds trailing-window
  transaction features. `POST /ingest/transaction` takes a **prepared feature
  row**, not a raw PaySim CSV line.

Do not describe either endpoint as "raw log ingestion" or "live feature
engineering." That is accurately covered — and explicitly deferred — in
`docs/RAW_LOG_INGESTION_ARCHITECTURE_EVALUATION.md`.

## Implementation

- `ml/models/cert_behavioral_scorer.py` — `CertBehavioralScorer`, a reusable
  scorer extracted from the replay CLI. Both `ml/replay_cert_assessments.py`
  (offline replay) and `POST /ingest/behavioral` (live) call the same
  `anomaly_scores` / `calibrated_risk` / `_top_deviations` functions from
  `ml/models/train_cert_behavioral_model.py`, so a live score is identical to a
  replayed one for the same window. Alerts only above `ALERT_RISK_THRESHOLD`
  (0.99, an empirical percentile, not a probability).
- `backend/app/core/live_scoring.py` — thin request models
  (`TransactionIngestRequest`, `BehavioralWindowIngestRequest`) and the
  score-then-ingest glue. Entity resolution prefers an explicit `entity_id`
  override, else resolves via `backend/app/shared/entity_mapping.py`, else
  falls back to `CERT:<user_id>` (matches prior replay behavior).
- `backend/app/main.py` — the two endpoints, guarded by the same
  `X-Ingestion-API-Key` check as `/assessments`. Scorers are constructed once
  and cached on `app.state` (lazy, since loading the CERT joblib bundle / SHAP
  explainer is expensive); tests inject tiny models via `create_app(...,
  fraud_scorer=..., cert_scorer=...)`.

## Demo

`data/synthetic/live_demo_behavioral_window.json` is a **real** anomalous CERT
window pulled from the prepared feature partitions (verified: scores 0.9992
through the committed model). `data/synthetic/live_demo_transaction.json` is a
**constructed** transaction with realistic drain-and-cash-out feature
magnitudes, scored live by the committed real fraud model (scores ~1.0). Both
are tagged to the same synthetic demo entity (`E027`) and time-aligned within
the 120-minute correlation window — this pairing is a demo construct, same
caveat as every other cross-domain link in this repo (see README "Honesty
notes").

```bash
rm -f data/incidents.db
VAULTWATCH_INGESTION_API_KEY=<key> python3 -m uvicorn backend.app.main:app --port 8000 &
VAULTWATCH_INGESTION_API_KEY=<key> python3 scripts/demo_live_ingest.py
```

Expected: both legs score live, the resulting incident shows
`confidence: high`, `access_decision: revoke`, `contributing_domains:
["ps1_behavioral", "ps2_transaction"]` — the core thesis, demonstrated live
rather than narrated from a snapshot.

## Tests

`backend/tests/test_ingest_transaction.py`, `backend/tests/test_ingest_behavioral.py`
(includes the end-to-end cross-domain corroboration test). Run with the rest of
the suite: `python3 -m pytest backend/tests ml/tests -q`.

## Out of scope

Raw log ingestion, live stateful feature engineering, Kafka raw-event
transport, new log-type handlers (Windows/Linux/HTTP/network) — see
`docs/RAW_LOG_INGESTION_ARCHITECTURE_EVALUATION.md` for that separate,
larger-effort track.
