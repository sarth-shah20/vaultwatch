# VaultWatch

**Cross-domain security correlation for banking.**
FinSpark Hackathon · Bank of Maharashtra · PS1 + PS2

VaultWatch fuses two normally-siloed bank security worlds — **employee behaviour**
(insider-threat / privileged-access signals) and **financial transactions** (fraud) —
into a single, explainable access decision for the *same person*. Its intelligence is
in **how it escalates**: a lone signal from either domain is treated cautiously, and only
**corroboration across both domains** unlocks the strongest response. That asymmetry is a
deliberate false-positive defence — nobody gets locked out on one noisy alert.

---

## Why this matters

Banks detect insider threats and payment fraud in **separate systems that never talk to
each other**. An attacker who trips one system just under its threshold, and the other
just under its threshold, slips through both. VaultWatch correlates the two: weak
evidence that *agrees across domains* outranks a single loud alert, so real coordinated
threats surface while everyday false positives stay quiet.

---

## What it does

| Capability | How |
|---|---|
| **Fuse two domains** | Behavioural anomalies (PS1) + transaction-fraud risk (PS2) are normalised into one shared `RiskAssessment` contract and joined per person. |
| **Bridge identities** | An entity-resolution crosswalk maps behavioural usernames ↔ transaction account IDs, so both signals land on the same human. |
| **Escalate by evidence** | A correlation engine raises confidence only when domains corroborate, then maps score + confidence to an action: **allow → throttle → step-up auth → revoke**. |
| **Keep analysts in the loop** | Acknowledge / escalate / dismiss drive an alert lifecycle; dismissals suppress future lone alerts for that entity. |
| **Look past today’s crypto** | A post-quantum module inventories the bank’s cryptography and prioritises *harvest-now-decrypt-later* (HNDL) exposure for PQC migration. |

### The dashboard (React + Tailwind)

- **Unified incidents** — the fused incident list; score gauges, confidence, decision tier, and which domain(s) fired, so the whole risk spectrum reads at a glance.
- **Incident detail** — split PS1 / PS2 evidence panels with per-signal weights; when only one domain fired, the *absence* of the other is shown explicitly.
- **PS1 / PS2 raw views** — what each detector sees alone, before correlation.
- **Quantum · PQC** — crypto inventory, HNDL exposure, and a prioritised migration list to NIST standards (ML-KEM / ML-DSA).

---

## Quickstart (runs entirely on committed demo data)

> No datasets, no Kafka, no model training required — the demo reads committed signal
> snapshots. **Prereqs:** Python 3.9+ and Node 18+.

```bash
# 1. Clone
git clone https://github.com/sarth-shah20/vaultwatch.git
cd vaultwatch

# 2. Backend API  (terminal 1)
python3 -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r backend/requirements.txt
python3 -m uvicorn backend.app.main:app --port 8000

# 3. Frontend dashboard  (terminal 2)
cd frontend
npm install
npm run dev
```

Open **http://localhost:5173**. The header should read **“Operational · 5 incidents.”**

The dev server proxies API calls to `localhost:8000`, so **no CORS setup is needed**.

<details>
<summary><b>Seeing fewer than 5 incidents?</b></summary>

The API seeds a SQLite store with `INSERT OR IGNORE`, so an old DB keeps stale rows.
Reset it once from the repo root and restart the backend:

```bash
rm -f data/incidents.db
```
</details>

---

## How the decision is made

```
per-domain RiskAssessment(s)
        │
        ▼
   fuse_scores()                     decide_access(score, confidence)
   ├─ ≥2 domains fire (≥0.5)         ├─ score ≥ 0.90 AND high  → REVOKE
   │   → boost + confidence = HIGH   ├─ score ≥ 0.70           → STEP-UP AUTH
   └─ lone signal                    ├─ score ≥ 0.40           → THROTTLE
       → confidence = LOW            └─ else                   → ALLOW
```

A **revoke requires both a high score AND corroboration** — a single strong signal, no
matter how loud, only earns step-up verification. This is the false-positive defence made
concrete.

### Live demo incidents

| Incident | Score | Confidence | Domains | Decision |
|---|---|---|---|---|
| INC-E027 / E029 / E028 | 0.95–0.98 | **high** | behavioural **+** transaction | **revoke** |
| INC-E010 | 0.78 | low | transaction only | step-up auth |
| INC-E015 | 0.60 | low | behavioural only | throttle |

---

## Architecture

```
   PS1 · BEHAVIOURAL (DetectionSample/)          PS2 · TRANSACTION (ml/)
   ┌───────────────────────────────┐            ┌───────────────────────────┐
   │ log stream → Kafka             │            │ PaySim → feature pipeline  │
   │   → drain3 template mining     │            │   → XGBoost fraud model    │
   │   → Isolation Forest scoring   │            │   → SHAP explanations      │
   └──────────────┬────────────────┘            └────────────┬──────────────┘
        anomaly_results.json                        RiskAssessment (per txn)
                  │                                            │
                  ▼                                            ▼
             ps1_adapter ──────►  ENTITY CROSSWALK  ◄────── fraud_scorer
                              (usernames ↔ account IDs)
                                        │
                                        ▼
                             CORRELATION ENGINE
                      fuse per-domain scores · gate on
                      corroboration · choose access tier
                                        │
                                        ▼
                    Incident store (SQLite) + alert lifecycle
                                        │
                     FastAPI  ──────────┴──────────  Quantum module
                (/incidents, feedback,               (crypto inventory,
                 /quantum/report)                     HNDL, PQC utils)
                                        │
                                        ▼
                        React + Tailwind dashboard
```

**Design principle:** detection and correlation are **decoupled**. Each detector runs on
its own and emits signals through a shared contract; VaultWatch consumes those signals and
correlates them. In production the detectors publish continuously; for a reproducible demo
we run the correlation layer on a **committed snapshot** of emitted signals. The
correlation, decisioning, and analyst workflow are all live — only ingestion is
pre-captured. (Decoupling detection from correlation is exactly how real SOC tooling is
built.)

---

## Repo layout

```
backend/app/
  shared/            RiskAssessment / UnifiedIncident contract shared across PS1 & PS2
  ps2_correlation/
    fraud_detection/    PaySim fraud scorer → RiskAssessment
    correlation_engine/ fuse_scores, decide_access, build_demo_incidents
    ps1_adapter.py      PS1 anomaly_results.json → RiskAssessment
  core/              SQLite incident store + alert-lifecycle state machine
  api/               response serialisation
  quantum_module/
    crypto_inventory/   quantum-risk scoring + PQC-migration prioritisation
    pqc_utils/          ML-KEM (Kyber) / ML-DSA (Dilithium) helpers
  main.py            FastAPI app (endpoints below)
  ../tests/          backend test suite

ml/
  data_pipeline/     PaySim feature engineering + demo-incident builders
  models/            trained fraud models (full + leakage-hardened) + trainer

DetectionSample/     PS1 streaming pipeline (Kafka producer/consumer, drain3,
                     Isolation Forest, Streamlit) — the behavioural detector

frontend/            React + Tailwind + Vite dashboard (primary UI)
dashboard/           earlier Streamlit dashboard (optional)
data/synthetic/      committed signal snapshots + entity crosswalk + crypto inventory
data/raw/            CERT + PaySim datasets (gitignored — see docs/DATASETS.md)
docs/                ARCHITECTURE · FEATURES · DATASETS · PS1_INTEGRATION · DEMO_SCENARIOS
```

---

## API

| Method | Endpoint | Purpose |
|---|---|---|
| `GET` | `/health` | status + incident count |
| `GET` | `/incidents` | all fused incidents (filters: `status`, `min_score`) |
| `GET` | `/incidents/{id}` | full incident with per-domain evidence |
| `POST` | `/incidents/{id}/feedback` | analyst action: `acknowledge` / `escalate` / `dismiss` |
| `GET` | `/suppressions` | entities suppressed by analyst dismissals |
| `GET` | `/quantum/report` | crypto inventory scored for quantum risk + PQC-migration priority |
| `POST` | `/assessments` | ingest already-scored `RiskAssessment`(s) (HTTP/Kafka transport) |
| `POST` | `/ingest/transaction` | score a prepared PaySim feature row **live** (in-process) and correlate |
| `POST` | `/ingest/behavioral` | score a prepared CERT behavioral window **live** (in-process) and correlate |

`/ingest/*` moves the live boundary from "already-scored assessment" to
"unscored feature input" — the server runs the model itself, not just the
correlation on top of it. See `docs/LIVE_SCORING.md`.

---

## Testing

```bash
pip install pytest httpx
python3 -m pytest backend/tests/ -q
```

---

## Advanced (optional — not needed for the demo)

<details>
<summary><b>Run the PS1 streaming detector (Kafka)</b></summary>

`DetectionSample/` is the real behavioural pipeline: `log_producer.py` streams logs to
Kafka, `drain3_consumer.py` mines event templates, `iforest_detector.py` scores anomalies,
and `streamlit_dashboard.py` visualises them. It requires a running Kafka broker and the
pipeline’s own dependencies. VaultWatch consumes its emitted `anomaly_results.json` — it
does **not** need Kafka running to correlate.
</details>

<details>
<summary><b>Retrain the fraud model</b></summary>

`ml/models/train_fraud_model.py` trains on PaySim (see `docs/DATASETS.md` for data setup).
It produces two artifacts: a full model and a **leakage-hardened** model (raw balances
removed) with precision-recall AUC ≈ 0.92 on a time-based holdout — the honest number used
for the demo.
</details>

---

## Honesty notes

We keep the demo defensible under scrutiny:

- **Batch snapshot for the demo** — see the architecture note above.
- **Entity crosswalk is a synthetic bridge** — PaySim and CERT are unrelated public
  datasets with no shared identities, so the username↔account mapping is clearly labelled
  synthetic (`data/synthetic/entity_mapping.json`). The *mechanism* is real; the specific
  links are constructed for the demo.
- **Two demo incidents are constructed** (E010, E015) and labelled as such, added so the
  dashboard shows the full decision spectrum, not only revokes.
- **Fraud model audited for leakage** — we investigated a near-perfect score, ran an
  ablation, and ship the hardened model.

---

## Tech stack

Python · FastAPI · XGBoost · SHAP · scikit-learn (Isolation Forest) · drain3 · Kafka ·
SQLite · React · Tailwind · Vite · kyber-py / dilithium-py (NIST PQC) · PaySim & CMU CERT datasets.
