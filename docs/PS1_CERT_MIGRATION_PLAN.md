# PS1 CERT Behavioral Migration and Live Integration

## Summary

Replace the DTAA TF-IDF keyword-anomaly detector as VaultWatch's primary PS1
source with a behaviorally grounded CERT model. Retain DTAA as a labeled legacy
streaming demonstration during a shadow period.

The migration includes:

- CERT preprocessing and behavioral-model training
- Email metadata ablation
- Timestamped, versioned `RiskAssessment` contracts
- Real two-hour temporal correlation
- HTTP and Kafka assessment ingestion
- Live incident re-correlation without restarting the API
- Explicit preservation of all synthetic identity caveats

## Implementation

### 1. Validate and prepare CERT data

Use only:

```text
data/raw/cert_insider_threat/
  users.csv
  logon.csv
  device.csv
  file.csv
  email.csv
```

Never mix in `data/raw/r4.2/`.

- Create a versioned data manifest recording schemas, row counts, date ranges,
  source URL, claimed release, source/release description, and file fingerprints.
- Treat this migration as unsupervised-only. Do not read, align, or gate work on
  `data/answers/`, and do not make label-based detection-performance claims.
- Validate unique event IDs within each file, parseable timestamps, email senders
  present in `users.csv`, and consistent user/PC identifiers.
- Process CSVs in chunks; never load the full email file into memory.
- Normalize events into partitioned Parquet with a common structure: event ID,
  timestamp, user, PC, event type, and source-specific attributes.
- Treat CERT timestamps as configured simulated-local time and normalize them
  consistently to UTC.

### 2. Build behavioral windows and baselines

Aggregate events into user-hour windows. Calculate baselines using past data only.

Feature groups:

- Context: off-hours activity, weekend activity, role, privilege indicator,
  employment-end proximity, and project/department context.
- Logon: count, unusual login hour, unique PCs, non-primary PC use, session
  duration, and PC novelty.
- Device: connection count, connection duration, unusual removable-media use,
  and file-tree novelty.
- File: open/write/copy/delete counts, removable-media direction, file-extension
  diversity, path novelty, and deviation from historical volume.
- Email `Send`: volume, external-recipient ratio, unique/new recipients, CC/BCC
  breadth, message size, attachment count, attachment bytes, and off-hours
  sending.
- Email `View`: volume, new senders, external senders, and off-hours viewing.

Exclude raw user IDs, PC IDs, event IDs, file paths, email addresses, and content
text from model features. Use them only to derive novelty and counts.

Build two feature variants:

1. Base: users + logon + device + file.
2. Email-enhanced: base features + email metadata.

### 3. Train and evaluate PS1

Use a hybrid behavioral approach:

- Per-user and role-peer robust baselines to calculate deviation features.
- `RobustScaler` followed by an `IsolationForest` with deterministic seed.
- Convert anomaly output into an empirical validation-percentile risk score;
  document that it is a relative behavioral risk, not a calibrated probability.
- Generate explanations from the largest behavioral deviations, such as unusual
  login time, new workstation, removable-media spike, or external-email burst.
- Compare the Isolation Forest against a transparent robust-z-score baseline.
- Use a chronological 60/20/20 train/validation/test split with all features
  calculated from prior history only.
- Compare models using chronological score stability, review-volume budgets,
  explanation quality, and sensitivity to documented synthetic perturbations.
- Promote the Isolation Forest only if it is at least as stable and operationally
  reviewable as the transparent baseline; otherwise ship the baseline scorer.
- Run the base-versus-email ablation and retain email features only if they add
  stable, interpretable signal without making review volume impractical.

Produce:

- Serialized scaler/model
- Feature-schema and model-metadata JSON
- Evaluation and ablation reports
- A committed, clearly labeled CERT assessment snapshot for the offline demo
- A replayable sequence of timestamped assessments for live demonstrations

### 4. Upgrade the shared assessment contract

Extend `RiskAssessment` while preserving backward loading of existing snapshots:

```text
assessment_id
schema_version
entity_id
domain
score
reasons
event_time
window_start
window_end
source
model_version
generated_at
```

Rules:

- `domain` is explicit rather than inferred only from reasons.
- `event_time` is the latest contributing event in the scored window.
- Each reason's domain must match the assessment domain.
- Scores must be finite and within `[0,1]`.
- Resolve known CERT users through the existing canonical mapping.
- Use deterministic `CERT:<user>` identities for unmapped users so PS1 can
  evaluate the full population; only explicitly mapped identities can correlate
  with PS2.
- Version and validate JSON using Pydantic transport schemas.

### 5. Add temporal correlation and persistence

- Persist assessments in SQLite with `assessment_id` uniqueness for idempotency.
- Correlate only assessments with the same canonical entity, different domains,
  and event times within a configurable window.
- Default correlation window: 120 minutes.
- Same-domain assessments may update the domain's strongest evidence but never
  count as corroboration.
- Signals outside the window create or update separate incidents.
- Handle out-of-order assessments by re-evaluating the affected entity's nearby
  windows.
- Generate a new UUID-backed incident ID when no compatible open incident exists.
- Keep current access thresholds initially, but move all correlation constants
  into documented configuration.
- Continue describing `high/low` as corroboration level, not statistical
  confidence.

### 6. Add live HTTP and Kafka ingestion

Create one shared `AssessmentIngestionService` used by both transports.

HTTP:

```text
POST /assessments
```

- Accept a versioned batch envelope.
- Validate all assessments.
- Require an environment-configured ingestion API key.
- Return accepted, duplicate, rejected, and affected incident IDs.
- Upsert/re-correlate incidents immediately.

Kafka:

```text
topic: vaultwatch.risk-assessments.v1
group: vaultwatch-correlation-v1
dlq:   vaultwatch.risk-assessments.v1.dlq
```

- Use the identical assessment schema.
- Provide at-least-once delivery with database idempotency.
- Commit offsets only after successful persistence and correlation.
- Send permanently invalid messages to the dead-letter topic with validation
  details.
- Support local plaintext Kafka for development and configurable security
  settings for deployment.

Add a CERT replay command that scores prepared windows and publishes them through
either HTTP or Kafka. This demonstrates live model-to-incident flow; do not claim
that raw CERT file ingestion itself is real-time.

### 7. Parallel cutover

Add configuration:

```text
PS1_PRIMARY_PROVIDER=dtaa|cert
PS1_SHADOW_PROVIDER=none|dtaa|cert
```

Rollout:

1. Keep DTAA primary while CERT runs in shadow mode.
2. Never fuse DTAA and CERT as separate corroborating domains; both are
   `ps1_behavioral`.
3. Compare alert volume, explanation quality, stability, and controlled
   perturbation sensitivity.
4. Promote CERT only after data, model, temporal-correlation, and ingestion gates
   pass.
5. Keep DTAA available for one migration cycle as a clearly labeled legacy
   streaming demo.
6. Regenerate demo artifacts from real CERT model outputs; do not retain hand-set
   PS1 scores.
7. Preserve the statement that CERT-to-PaySim identities and time alignment remain
   synthetic.
8. Correct documentation that currently describes DTAA identities or anomalies as
   CERT evidence.

## Test and Acceptance Plan

- CSV contract tests for every CERT source, including quoted email content,
  `Send/View`, external recipients, and attachment-path parsing.
- Chunked and full-fixture processing must produce identical aggregates.
- Tests proving no raw identifiers or future events enter model features.
- Deterministic training and risk scoring under a fixed seed.
- Explanation tests mapping top deviations to structured `Reason` objects.
- Unsupervised stability, review-volume, perturbation, and base/email ablation
  reports before promotion.
- Backward-compatibility tests for existing assessment snapshots.
- Temporal tests: inside/outside two hours, same-domain duplicates, out-of-order
  events, and unmapped CERT users.
- HTTP tests for validation, authentication, duplicate ingestion, and immediate
  incident updates.
- Kafka tests for schema parity, retries, idempotency, offset handling, and
  dead-letter behavior.
- End-to-end replay test: CERT window -> model score -> HTTP/Kafka -> stored
  assessment -> correlated incident -> API/dashboard, without API restart.
- Existing five-incident demo must remain operational under the DTAA compatibility
  flag until CERT promotion.

## Assumptions and Boundaries

- The new `email.csv` belongs to the same population as the larger CERT files;
  full sender-coverage validation remains mandatory.
- Ground-truth answer files are intentionally outside this unsupervised migration;
  they must not gate preprocessing, training, evaluation, or promotion.
- PaySim and PS2 model retraining are outside this migration.
- The CERT-to-PaySim identity bridge remains synthetic and must stay labeled.
- Raw event streaming and production bank connectors are future work; this
  migration provides live ingestion of scored assessments.
- Broader API authorization, production database migration, PS2 calibration, and
  graded statistical confidence remain separate technical-debt projects.

## Implementation Status

### Step 1 — Complete (2026-07-23)

- Pipeline: `ml/data_pipeline/prepare_cert_data.py`
- Tracked manifest: `data/manifests/ps1_cert_data_manifest.json`
- Generated dataset: `data/processed/ps1/cert_events/` (ignored by Git)
- Validated population: 4,000 users and 18,091,953 activity events
- Result: zero duplicate event IDs, missing required values, unknown users,
  malformed user/PC IDs, or unexpected activity types
- Timestamp setting: simulated-local `UTC`, preserving the dataset's displayed
  clock hours; change only with documented source-timezone evidence
- Rebuild command:
  `.venv/bin/python3 -m ml.data_pipeline.prepare_cert_data`

### Step 2 — Complete (2026-07-23)

- Pipeline: `ml/data_pipeline/cert_behavioral_windows.py`
- Tracked manifest: `data/manifests/ps1_cert_behavioral_features.json`
- Generated bundle: `data/processed/ps1/cert_behavioral_windows/` (ignored by
  Git)
- Output: 6,792,414 active user-hour windows in each variant across 516 UTC
  dates; 60 base model features and 100 email-enhanced model features
- Baselines: 30 prior calendar days only, with a seven-day cold-start period,
  user and role-peer rolling medians, and robust scale from within-day MAD and
  between-day IQR
- Stable-zero histories use documented unit-aware scale floors so a later burst
  is not incorrectly assigned a zero deviation
- Causal state derives new PCs, device trees, file paths, recipients, senders,
  primary-PC deviations, and matched logon/device session durations
- Raw event/PC/path/address/content fields are excluded from both model variants;
  `user_id` remains an identifier and is explicitly excluded from model columns
- Rebuild command:
  `.venv/bin/python3 -m ml.data_pipeline.cert_behavioral_windows`


### Step 3 — Complete (2026-07-23)

- Pipeline: `ml/models/train_cert_behavioral_model.py`
- Tracked report: `data/manifests/ps1_cert_training_report.json`
- Ignored artifacts: `ml/models/cert_behavioral_*.joblib` and
  `data/processed/ps1/cert_model/*_test_snapshot.json`
- Chronological split: 309 train, 103 validation, 104 test UTC dates; train and
  evaluation samples are deterministic and stratified by date
- Models: 150-tree Isolation Forest over train-only variance-filtered,
  RobustScaler-transformed features; 60 base and 100 email-enhanced features
  retained
- Selection: email-enhanced is shadow candidate because sampled test daily alert
  rate is lower (1.31% vs 1.43%) and more stable (CV 0.532 vs 0.618)
- Validation: controlled perturbations raised risk for 100% of 5,000 sampled
  test windows in both variants; this is sensitivity evidence, not detection
  performance
- Caveat: robust-z baseline often reaches clip 25; retain it for explanations,
  not independent access decisions
- Status: experimental/shadow-only. No labels, answer key, PR-AUC, recall, or
  calibrated-probability claim.
- Rebuild command:
  `.venv/bin/python3 -m ml.models.train_cert_behavioral_model`

### Step 4 — Complete (2026-07-23)

- Added backward-compatible, Pydantic-validated `RiskAssessmentTransport` schema.
- Added explicit `domain`, `assessment_id`, `schema_version`, `event_time`,
  `time_basis`, `window_start`, `window_end`, `source`, and `model_version` fields to
  `RiskAssessment`.
- Legacy PS1/PS2 snapshots still load; compatibility boundary ignores only
  non-contract legacy metadata.
- PS1 and PS2 producers emit explicit domains, stable replay IDs, and source/model
  metadata. PaySim always derives timestamps from one fixed step-to-UTC mapping
  and marks them `synthetic_step_mapping`.
- CERT test snapshots now include latest contributing `event_time` plus scored
  `window_start`/`window_end`.
- Pydantic contract tests cover score bounds, reason-domain consistency, stable
  IDs, timestamp round-trips, and legacy loading.
- Scope boundary: HTTP/Kafka ingestion remains Step 6.

### Step 7 — Complete (2026-07-23)

- Provider config: `PS1_PRIMARY_PROVIDER=dtaa|cert` and
  `PS1_SHADOW_PROVIDER=none|dtaa|cert`. Defaults are DTAA primary and CERT
  shadow; same provider cannot be both.
- Runtime selection/comparison: `backend/app/ps1_insider_threat/providers.py`.
  It records alert count, entity count, explanation presence, score summary,
  source, and model version as operational comparison—not labeled performance.
- Both providers remain `ps1_behavioral`. The temporal engine retains only the
  strongest same-domain evidence; DTAA plus CERT can never raise cross-domain
  corroboration by themselves.
- `GET /providers` exposes resolved policy and explicitly reports
  `shadow_counts_as_corroboration: false`.
- CERT artifact remains real model output. CERT↔PaySim identity bridge and
  global clock remain synthetic and are only demo/integration constructs.
- DTAA legacy provider remains available for one migration cycle.

### Step 6 — Complete (2026-07-23)

- Shared service: `backend/app/core/assessment_ingestion.py`. It validates the
  versioned envelope per assessment, records accepted/duplicate/rejected
  outcomes, persists through `TemporalCorrelationStore`, then projects affected
  incidents into API SQLite store.
- HTTP: `POST /assessments`, guarded by `VAULTWATCH_INGESTION_API_KEY` through
  `X-Ingestion-API-Key`. An unset key returns 503; wrong key returns 401.
- Kafka adapter: `backend/app/ps2_correlation/correlation_engine/kafka_ingestion.py`.
  Topic/group/DLQ are `vaultwatch.risk-assessments.v1`,
  `vaultwatch-correlation-v1`, and `vaultwatch.risk-assessments.v1.dlq`.
  Commit follows successful persistence or successful DLQ publication. Local
  plaintext and configurable SASL/security fields are supported.
- Replay: `ml/replay_cert_assessments.py` scores prepared CERT behavioral
  windows with saved email-enhanced model, emits same envelope over HTTP/Kafka.
  This is replay of prepared windows, not real-time raw CERT CSV ingestion.

### Step 5 — Complete (2026-07-23)

- SQLite ledger: `backend/app/ps2_correlation/correlation_engine/store.py`.
  `risk_assessments.assessment_id` is unique, so replay is idempotent.
- Correlation policy: `backend/app/ps2_correlation/correlation_engine/config.py`.
  Default window is 120 minutes; thresholds retain legacy operating policy and
  are explicitly not calibrated probabilities.
- Temporal rule: only one canonical entity, different domains, and event times
  inside same fixed window can corroborate. Missing timestamps never corroborate.
- Same-domain records retain only strongest evidence in each window. Signals
  outside window become separate UUID-backed incidents.
- Out-of-order arrival re-windows all stored assessments for affected entity,
  preserving compatible incident ID where possible.
- `high` / `low` remain corroboration levels, not statistical confidence.
- Demo regeneration: `build_demo_incidents()` now inserts committed CERT and
  PaySim assessments into in-memory SQLite engine, then returns materialized
  incidents. CET3786 end-to-end regression verifies high corroboration + revoke.
- Scope boundary: HTTP/Kafka ingestion remains Step 6.

