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
- Treat the Kaggle activity files and the separately downloaded official CMU
  `answers.tar.bz2` as untrusted with respect to each other until an explicit
  release-alignment check passes. A matching `r4.2` name or source description is
  not sufficient evidence of compatibility.
- Parse `data/answers/insiders.csv` for all r4.2 incidents and build a ground-truth
  alignment report containing every malicious username, scenario, start/end time,
  detailed-observables file, and expected event types.
- Require every r4.2 malicious username to exist in the Kaggle `users.csv` and in
  at least one local activity file. For each answer-key observable whose source is
  locally available (`logon`, `device`, `file`, or `email`), require its event ID
  and user/timestamp tuple to resolve to the corresponding activity CSV. Report
  unsupported sources such as a missing `http.csv` separately; never count them as
  successful matches.
- Verify that every scenario interval falls inside the local activity date range,
  and report per-scenario/per-source expected, matched, and missing observables.
  Event-ID mismatches may be investigated with user/timestamp tuple matching, but
  a fallback match is diagnostic only unless the mirror's documented transformation
  explains it.
- Make this alignment report a hard gate: any missing malicious username, an
  incompatible user population/schema, or unexplained missing observable from an
  available source fails ground-truth compatibility. On failure, stop before
  label-based splitting, training, evaluation, or performance claims and obtain
  either the canonical matching r4.2 activity files or the answer key matching the
  Kaggle mirror. Never remap answer-key usernames to make the gate pass.
- Pipeline plumbing may be developed before alignment passes, but the activity
  data must remain unlabeled and the model experimental/shadow-only.
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
- Once the matching ground truth is available, select the model using
  incident-level PR-AUC, detection delay, and recall at a fixed
  false-positive-per-user/day budget.
- Promote the Isolation Forest only if it outperforms the transparent baseline at
  the same false-positive budget; otherwise ship the baseline scorer.
- Run the base-versus-email ablation and retain email features only if they improve
  incident detection without worsening the selected false-positive budget.

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
3. Compare alert volume, explanation quality, stability, and labeled CERT
   performance.
4. Promote CERT only after data, ground-truth, model, temporal-correlation, and
   ingestion gates pass.
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
- Ground-truth alignment tests covering complete r4.2 username membership,
  scenario date-range coverage, exact event-ID/user/timestamp matching by source,
  unsupported-source reporting, and a deliberately mismatched fixture that must
  fail closed.
- Chunked and full-fixture processing must produce identical aggregates.
- Tests proving no raw identifiers or future events enter model features.
- Deterministic training and risk scoring under a fixed seed.
- Explanation tests mapping top deviations to structured `Reason` objects.
- Ground-truth evaluation plus base/email ablation before promotion.
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
- The activity files came from a Kaggle mirror while `data/answers/` came directly
  from CMU SEI. The answer key is usable only if the explicit release-alignment
  gate passes. Without a passing report, CERT remains experimental/shadow and no
  supervised performance claim is published.
- PaySim and PS2 model retraining are outside this migration.
- The CERT-to-PaySim identity bridge remains synthetic and must stay labeled.
- Raw event streaming and production bank connectors are future work; this
  migration provides live ingestion of scored assessments.
- Broader API authorization, production database migration, PS2 calibration, and
  graded statistical confidence remain separate technical-debt projects.
