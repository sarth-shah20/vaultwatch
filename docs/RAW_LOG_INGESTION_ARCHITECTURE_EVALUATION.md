# Raw Log Ingestion Architecture Evaluation

## Decision

VaultWatch should add a raw-log ingestion layer, but should not replace the
existing assessment ingestion and correlation path.

Recommended flow:

```text
Servers / agents / transaction systems
        |
        v
FastAPI batch ingestion (`POST /logs/batch`)
        |
        v
Durable raw-event store + bounded processing queue
        |
        v
Time/count-triggered window processor
        |
        v
Incremental feature engineering and behavioral baselines
        |
        v
PS1/PS2 scoring -> versioned RiskAssessment
        |
        v
Existing assessment ingestion -> temporal correlation -> incidents
        |
        v
API/dashboard notifications
```

FastAPI should be the simple, demonstrable ingestion boundary. Kafka should
remain an optional transport for deployments that already operate a reliable
streaming platform or require distributed buffering. SQLite should remain a
local/demo backend, not the claimed storage solution for bank-scale raw logs.

## Why this change is needed

Current live path begins after model scoring:

- `POST /assessments` accepts up to 1,000 versioned `RiskAssessment` objects.
- `AssessmentIngestionService` stores assessments, re-correlates incidents, and
  projects them into the API incident store.
- Kafka carries the same scored-assessment envelope.
- `ml/replay_cert_assessments.py` reads prepared CERT windows, scores them, and
  publishes assessments.
- CERT CSV normalization, behavioral-window construction, and historical
  baselines remain offline jobs.

Therefore current system can truthfully claim live assessment ingestion and
incident re-correlation. It cannot yet claim live raw security-log ingestion,
live feature generation, or production-scale stream processing.

## Evaluation of proposed winning architecture

### Useful ideas to adopt

- Persist raw events before ML so replay and audit remain possible.
- Normalize heterogeneous sources behind one versioned event contract.
- Build employee/entity timelines rather than classifying isolated logs.
- Process bounded batches/windows for throughput and behavioral context.
- Store predictions and evidence separately from raw logs.
- Keep correlation after domain scoring.
- Push incident changes to dashboard without API restart.

### Claims that need qualification

#### “Batch after 100 logs”

One fixed count is not enough. Low-volume entities could wait indefinitely,
while high-volume entities could mix unrelated users and time periods.

Use three triggers:

- maximum event count;
- maximum wait time;
- event-time window completion.

Recommended demo defaults:

```text
max_batch_events = 500
max_batch_wait_seconds = 2
behavior_window_minutes = 60
allowed_lateness_minutes = 5
```

These are operating defaults, not ML-derived optimal values. Make them
configuration and tune them with load tests.

#### “ML performs better on batches”

Batching improves throughput. Behavioral models improve because they receive
time-window and history features, not because a batch happened to contain 100
rows. Feature semantics must remain identical between training and live scoring.

#### “SQLite stores millions of bank logs”

SQLite is appropriate for a single-process demonstration and modest replay. It
does not provide the horizontal write scaling, retention management, replication,
or concurrent analytical querying expected for a bank.

Use:

- local/hackathon: SQLite in WAL mode;
- pilot: PostgreSQL for metadata/incidents plus object storage or ClickHouse for
  append-heavy raw events;
- large deployment: partitioned event store plus Kafka/Pulsar or managed queue,
  with multiple consumers and explicit retention.

#### “Kafka cannot handle bank volume”

Kafka can handle high volume when deployed with multiple brokers, partitions,
replication, capacity planning, monitoring, and consumer scaling. Current
single-broker demo proves integration semantics, not bank-scale capacity.

The concern is operational complexity, not Kafka’s basic throughput capability.
VaultWatch should not require Kafka for its hackathon demonstration.

## Target architecture profiles

### Profile A — hackathon/local

```text
Log replay/agent
  -> FastAPI batch endpoint
  -> SQLite raw_events (WAL)
  -> in-process bounded queue
  -> one background window worker
  -> CERT model
  -> existing /assessments service
  -> SQLite incidents
  -> dashboard polling or WebSocket notification
```

Purpose: demonstrate complete raw event -> incident flow with minimal
infrastructure. This profile must state that SQLite and one worker are demo
choices.

### Profile B — production-shaped pilot

```text
Collectors
  -> load-balanced ingestion API
  -> durable event store / queue
  -> partitioned window workers (entity_id + time)
  -> model-serving workers
  -> assessment ledger
  -> temporal correlation workers
  -> PostgreSQL incidents
  -> WebSocket/SSE gateway
```

Kafka is optional between ingestion and workers. If used, partition raw events
by canonical entity or stable source identity so one entity’s ordering is
preserved.

### Profile C — bank-scale deployment

Requires workload sizing before technology selection:

- peak and sustained events per second;
- average and maximum event size;
- number of servers/accounts/entities;
- retention and legal-hold duration;
- replay/reprocessing frequency;
- acceptable ingestion and alert latency;
- regional availability and disaster recovery;
- encryption, key management, tenant isolation, and audit requirements.

This profile is infrastructure and security engineering work, not a direct
extension of the current SQLite demo.

## Required code changes

### 1. Raw event contract

Add:

```text
backend/app/shared/raw_event_schema.py
```

Define versioned `RawEventEnvelope` and `RawEvent`:

```text
event_id
schema_version
source_type
event_time
received_at
source_system
entity_hint
host
event_type
attributes
```

Rules:

- `event_id` required and unique for idempotency;
- preserve original timestamp plus normalized UTC timestamp;
- reject unbounded payloads and unknown schema versions;
- keep source-specific fields inside bounded `attributes`;
- never accept secrets, raw credentials, or unrestricted email/file content.

### 2. Raw log API

Change:

```text
backend/app/main.py
```

Add:

```text
POST /logs/batch
GET  /logs/ingestion-status
```

Responsibilities:

- authenticate producer;
- validate envelope;
- persist accepted events before acknowledgment;
- return accepted/duplicate/rejected counts;
- apply request-size and batch-size limits;
- expose queue depth and oldest-unprocessed age.

Do not route raw logs through `AssessmentIngestionService`; raw events and scored
assessments are different contracts.

### 3. Source handlers and normalization

Add:

```text
backend/app/raw_ingestion/handlers/base.py
backend/app/raw_ingestion/handlers/logon.py
backend/app/raw_ingestion/handlers/device.py
backend/app/raw_ingestion/handlers/file.py
backend/app/raw_ingestion/handlers/email.py
backend/app/raw_ingestion/handlers/http.py
backend/app/raw_ingestion/handlers/network.py
backend/app/raw_ingestion/handlers/windows.py
backend/app/raw_ingestion/handlers/linux.py
```

Start with CERT-compatible logon/device/file/email handlers because current PS1
model has matching feature definitions. HTTP/network/Windows/Linux require new
feature contracts and usually new models; do not pretend existing CERT model can
score them.

### 4. Raw event storage abstraction

Add:

```text
backend/app/raw_ingestion/store.py
backend/app/raw_ingestion/config.py
```

Local SQLite tables:

```text
raw_events(event_id PK, source_type, event_time, entity_key, payload, status)
processing_leases(window_key PK, owner, leased_until)
processing_checkpoints(partition_key PK, watermark, updated_at)
```

Requirements:

- `INSERT OR IGNORE` idempotency;
- WAL mode and short transactions;
- indexes on entity/time, source/time, and processing status;
- explicit retention cleanup;
- bounded reads;
- storage interface allowing later PostgreSQL/ClickHouse implementation.

Do not reuse `TemporalCorrelationStore.risk_assessments` for raw events.

### 5. Batch/window manager

Add:

```text
backend/app/raw_ingestion/batch_manager.py
backend/app/raw_ingestion/worker.py
```

Responsibilities:

- trigger on count, wait time, or event-time watermark;
- partition by canonical entity and hour;
- handle late/out-of-order events;
- checkpoint completed windows;
- retry transient failures;
- quarantine permanently invalid windows;
- expose backlog and processing latency.

Use a bounded queue. When full, return `429`/`503` or stop consuming from the
external broker; never allow unbounded memory growth.

### 6. Live feature parity

Refactor:

```text
ml/data_pipeline/cert_behavioral_windows.py
```

Extract source-independent functions into:

```text
ml/features/cert_window_features.py
ml/features/baseline_state.py
```

Both offline training and live worker must call the same feature functions.
Persist:

- user baseline state;
- role-peer baseline state;
- primary/new PC state;
- recipient/path/device novelty state;
- prior-window counters and watermarks.

This is the highest-risk engineering part. Feature drift between offline and
live paths would invalidate model scores even if API and queue work perfectly.

### 7. Live CERT scorer

Refactor:

```text
ml/replay_cert_assessments.py
```

Extract reusable scorer:

```text
ml/models/cert_behavioral_scorer.py
```

Worker input: completed behavioral window.

Worker output: existing validated `RiskAssessmentTransport`, then call the
existing `AssessmentIngestionService`.

Keep `replay_cert_assessments.py` as a CLI wrapper around the same scorer.

### 8. Transaction/raw PS2 path

Add separately:

```text
backend/app/raw_ingestion/handlers/transaction.py
backend/app/ps2_correlation/fraud_detection/transaction_service.py
```

Use current PaySim scorer for demo-compatible transaction events. Do not combine
raw security-log and transaction schemas into one untyped object.

### 9. Optional transport adapters

Keep:

```text
backend/app/ps2_correlation/correlation_engine/kafka_ingestion.py
```

Its current topic carries assessments. If raw-event Kafka is added, use a
different topic and consumer group:

```text
vaultwatch.raw-events.v1
vaultwatch-raw-windowing-v1
vaultwatch.raw-events.v1.dlq
```

Both REST and Kafka adapters must call the same raw-ingestion service. Avoid two
independent parsing/storage implementations.

### 10. Dashboard delivery

Change:

```text
backend/app/main.py
dashboard/client.py
dashboard/app.py
```

Add WebSocket or server-sent-event incident notifications only after durable
incident upsert. Keep existing REST reads as recovery/source of truth.

Dashboard should show:

- ingestion rate;
- raw-event backlog;
- oldest unprocessed event;
- completed windows;
- model alerts;
- correlated incidents;
- storage/worker health.

### 11. Configuration

Add documented environment settings:

```text
RAW_INGESTION_BACKEND=sqlite|postgres|kafka
RAW_BATCH_MAX_EVENTS=500
RAW_BATCH_MAX_WAIT_SECONDS=2
RAW_WINDOW_MINUTES=60
RAW_ALLOWED_LATENESS_MINUTES=5
RAW_QUEUE_MAX_EVENTS=10000
RAW_EVENT_RETENTION_DAYS=7
RAW_MAX_REQUEST_BYTES=5242880
```

Production values must come from measured traffic and analyst-latency targets.

## Testing required

### Contract and correctness

- valid/invalid fixture per log type;
- duplicate `event_id` across REST and Kafka;
- timestamp normalization;
- late and out-of-order events;
- chunked vs replayed feature parity;
- offline vs live feature-vector equality;
- window replay idempotency;
- worker crash/restart from checkpoint;
- malformed-event quarantine/DLQ;
- raw event -> feature window -> score -> assessment -> incident -> dashboard.

### Load and resilience

Hackathon acceptance target:

- sustain 1,000 small events/second for 10 minutes on development hardware;
- zero accepted-event loss;
- bounded queue memory;
- p95 ingestion acknowledgment under 500 ms;
- completed-window p95 latency under 10 seconds after watermark;
- restart preserves raw events and resumes unfinished windows;
- API returns controlled backpressure when queue/store is unavailable.

These are proposed demonstration targets, not bank-scale claims.

For a bank pilot, derive targets from measured peak traffic and test at least
2x expected peak with realistic payload sizes and retention.

## Delivery plan and effort

Estimates assume one engineer familiar with this repository, existing CERT
artifacts available, and no production cloud/infrastructure procurement.

| Phase | Work | Estimate |
|---|---|---:|
| 0 | Contracts, source inventory, load assumptions, ADR | 1–2 days |
| 1 | Raw schema, batch API, auth, idempotent SQLite store | 2–3 days |
| 2 | CERT logon/device/file/email handlers | 2–4 days |
| 3 | Batch/window manager, watermarks, checkpoints, retries | 3–5 days |
| 4 | Refactor offline/live feature parity and baseline state | 5–8 days |
| 5 | Reusable CERT scorer and assessment integration | 2–3 days |
| 6 | Transaction handler and PS2 live scoring path | 2–4 days |
| 7 | Dashboard live notification and ingestion-health views | 2–4 days |
| 8 | End-to-end, restart, parity, and local load tests | 3–5 days |
| 9 | Documentation, demo replay, failure runbook | 1–2 days |

### Totals

- Thin hackathon MVP: 7–10 engineering days. Includes raw batch API, SQLite,
  CERT-compatible handlers, one-hour windows, scorer integration, and basic
  dashboard status. Reduced resilience and source coverage.
- Credible complete local architecture: 20–35 engineering days.
- Production-shaped pilot with PostgreSQL/ClickHouse, managed queue, deployment,
  monitoring, security review, and performance testing: 6–10 weeks for 2–3
  engineers.
- Bank production rollout across hundreds of servers: typically 3–6+ months for
  a cross-functional team; depends on collectors, identity mapping, retention,
  network/security approval, HA/DR, and compliance.

## Recommended implementation order

1. Build REST batch ingestion and durable raw-event SQLite store.
2. Support CERT logon/device/file/email shapes only.
3. Refactor feature functions for offline/live parity.
4. Generate a real CERT `RiskAssessment` from a completed live window.
5. Feed it through existing assessment/correlation engine.
6. Show raw event, feature evidence, assessment, and incident in dashboard.
7. Load-test and document local limits.
8. Add Kafka raw-event adapter only if time remains or deployment requires it.
9. Add Windows/Linux/network/HTTP models only with matching data and evaluation.

## Go/no-go recommendation

Proceed with Profile A if goal is a stronger hackathon demonstration. It closes
the largest honesty gap: current “live” flow starts at scored assessments.

Do not attempt to claim Profile C from SQLite plus a batch of 100. For bank-scale
discussion, present Profile B/C as deployment architecture and show measured
Profile A results.

Kafka work should remain in repository because assessment-level Kafka delivery,
idempotency, offset handling, and DLQ behavior are already proven. Reposition it
as optional infrastructure, not mandatory raw-log processing.
