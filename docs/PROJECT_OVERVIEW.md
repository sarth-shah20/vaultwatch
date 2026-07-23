# VaultWatch — Complete Project Explainer (Backend + ML)

This document explains the whole backend/ML system in plain English: what each
piece does, why it was built that way, what data feeds it, and how everything
connects. It intentionally skips the frontend (React dashboard) — that's a
separate, upcoming rework. Read this top to bottom once, then use it as a map
whenever you need to jump into a specific part of the code.

If you only remember one sentence: **VaultWatch takes two weak, separate
warning signs — one about how a person behaves at work, one about a suspicious
transaction — and only raises a serious alarm when the same person trips both
in a short time window.** Everything below is the machinery that makes that
one sentence real, explainable, and (as of the latest work) live.

---

## 1. The problem, restated simply

Banks run two kinds of security systems today, and they don't talk to each
other:

1. **Insider-threat / behavioral systems** watch what employees, contractors,
   and admins *do* — when they log in, what machines they touch, what files
   they move, who they email. (This is **PS1**.)
2. **Fraud-detection systems** watch *transactions* — money moving between
   accounts, looking for patterns like "drain an account, then cash out."
   (This is **PS2**.)

A smart attacker (or a compromised/malicious insider) can often stay just
under the alert threshold of *each* system individually. But if you look at
**both systems together, for the same person, in the same time window**, the
combined picture is far more convincing than either alert alone. That
"look at both together" step is the actual product. Everything else — the
models, the data pipelines, the APIs — exists to feed that one correlation
decision with trustworthy, explained evidence.

VaultWatch's answer, concretely:

- **One shared identity** for a person across both worlds (an "entity").
- **One shared output shape** for any risk signal, from any detector — a
  `RiskAssessment`, always carrying *why* it fired, never just a number.
- **One correlation engine** that only escalates to the strongest response
  (revoke access) when two *independent* domains agree, inside a time window.
  A lone signal — no matter how loud — gets a softer response (step-up
  authentication or throttling), never an automatic revoke.

That asymmetry — corroboration required for the harshest action — is the
concrete answer to "reduce false positives" from the problem statement. It's
not a vague claim; it's one `if` statement in the code (`decide_access`,
section 8 below), and it's tested.

---

## 2. The shared language everything speaks

Before any detector, model, or API existed, the team agreed on a few shared
data shapes. This was deliberate — see `CLAUDE.md` principle #1: *"Don't
create parallel/duplicate models per module."* Every part of the system reads
and writes these same shapes, defined once in `backend/app/shared/entities.py`.

### Entity
A person, or anything that acts like one: a human employee, a service
account, or an automation/script. One entity can show up in CERT logs (as a
username) *and* in PaySim transactions (as an account) *and* in a
telemetry feed (as a device/IP) — the whole point of an entity is to be the
one thing all three worlds can point at.

### Reason
A single, structured piece of evidence: *which signal fired* (`signal_name`),
*from which domain* (`ps1_behavioral` / `ps2_transaction` / `quantum`), *how
much it contributed* (`weight`, 0–1), and a human-readable *raw value*
(e.g. `"accessed at 02:14 IST"` or `"error_balance_orig=0; raises fraud
risk"`). Nothing in this system is allowed to raise an alert with just a bare
number — see `CLAUDE.md` principle #2. Every score-producing function builds
a list of these from the moment it computes a score, not after the fact as an
afterthought.

### RiskAssessment
The universal output of *any* scoring component — PS1's behavioral model,
PS2's fraud model, or (eventually) a telemetry model. It carries:
- `entity_id`, `score` (0–1), `reasons` (list of `Reason`)
- `domain` — which world this came from
- `event_time` / `window_start` / `window_end` — when the *evidence* happened
  (not when the model happened to run)
- `source` and `model_version` — which detector/model produced it, and which
  version, so you can always trace a score back to the code that made it
- `assessment_id` — a stable, deterministic ID (see §7) so the same evidence
  replayed twice doesn't create two records

This is the one shape both PS1 and PS2 "speak." A fraud score and a
behavioral anomaly score look identical on the wire — same fields, same
rules — which is exactly what lets one correlation engine treat them
uniformly instead of needing PS1-specific and PS2-specific fusion logic.

### UnifiedIncident
The actual bridge object mentioned in `docs/ARCHITECTURE.md`: one or more
`RiskAssessment`s for the same entity, fused into a single combined score, a
corroboration level (`high`/`low`), and an `AccessDecision`.

### AccessDecision
Risk-based access control must *do* something, not just display a number —
`CLAUDE.md` principle #4. The only four allowed outcomes: `allow`,
`throttle`, `step_up_auth`, `revoke`. Every combined score gets mapped to
exactly one of these by `decide_access()` (§8).

Why build this shared contract *first*, before any model? Because it means
PS1's model and PS2's model can be built, tested, and even completely
replaced independently (the CERT/DTAA swap in §4 is proof this works) without
ever touching the correlation engine. The contract is the seam that lets two
different people work in parallel without stepping on each other.

---

## 3. What data is used for what

No single public dataset covers "insider behavior + bank transactions"
together — nobody publishes that combination, for obvious privacy reasons. So
the system is built from two real public datasets plus a synthetic bridge
layer built by the team. Being upfront about which parts are real and which
are constructed is a running discipline throughout this document — look for
the **"real" / "constructed" / "synthetic"** labels.

| Dataset | Used for | Real or synthetic? |
|---|---|---|
| **CMU CERT Insider Threat** (`users.csv`, `logon.csv`, `device.csv`, `file.csv`, `email.csv`) | PS1 behavioral model — training and scoring | Synthetic-but-realistic activity logs, published by CMU for insider-threat research. Not real bank data, but a real, standard research dataset (not something we invented). |
| **PaySim** (`~6.3M` simulated mobile-money transactions) | PS2 fraud model — training and scoring | Simulated transactions (a Kaggle dataset), not real bank data, but the fraud *patterns* (drain-then-cash-out) are realistic and the transactions/labels are the dataset's own, not hand-set by us. |
| **DTAA logs** (`DetectionSample/sample_logs.csv`) | Legacy/shadow PS1 detector (drain3 + Isolation Forest on log text) | A teammate-provided sample log set, used only by the older/shadow pipeline, being phased out (see §4). |
| **Entity crosswalk** (`data/synthetic/entity_mapping.json`) | Bridges a CERT username, a PaySim account, and telemetry IDs onto one `entity_id` | **Fully synthetic / hand-built.** This is the single most important honesty caveat in the whole project — see §7. |
| **Demo scenario crosswalk** (`data/synthetic/cert_paysim_global_demo_crosswalk.json`, `demo_scenarios.json`) | Pairs real CERT anomalies with real PaySim fraud rows, for the same bridged entity, within a shared time window | Built by `ml/data_pipeline/scenario_builder.py` from **real** model outputs and **real** fraud labels — the pairing/timing is a synthetic construct, but nothing about the individual signals is faked. |
| **Crypto inventory** (`data/synthetic/crypto_inventory.json`) | Quantum/PQC module | 12 made-up bank systems (e.g. "Customer PII vault" using RSA-2048) — there's no dataset for this; it's a spreadsheet-style stand-in for "what a real crypto audit would produce." |
| **CERT ground-truth answer key** (`data/answers/`) | **Deliberately never used** | CERT ships a labeled list of which users are actually malicious insiders. VaultWatch's PS1 model is trained as **unsupervised** (no labels) on purpose — see §4 — and this migration explicitly forbids reading `data/answers/` to tune or gate anything. It exists on disk only because it shipped with the dataset download. |

Raw datasets (`data/raw/`) are gitignored — too large to commit, and a fresh
clone can't retrain without downloading them (see `docs/DATASETS.md`). What
*is* committed: trained model artifacts small enough to check in
(`ml/models/fraud_model*.json`), and small labeled JSON snapshots
(`data/synthetic/*.json`) so the whole demo runs on a fresh clone with zero
downloads.

---

## 4. PS1 — the behavioral / insider-threat engine

PS1's job: look at what a person *does* on company systems, and produce a
risk score when their behavior deviates unusually from their own normal
pattern (and their peers').

### Two detectors exist, on purpose, during a migration

There are actually **two** PS1 detectors in this repo right now, because the
team is mid-migration from an early prototype to a properly-grounded one.
Both speak the exact same `domain="ps1_behavioral"` output, and there's a
hard rule enforced in code: **they can never both count as corroborating
evidence for each other** (that would be double-counting one domain as two).
This is controlled by `backend/app/ps1_insider_threat/providers.py`:

```
PS1_PRIMARY_PROVIDER=cert   # default — the real behavioral model
PS1_SHADOW_PROVIDER=dtaa    # default — kept running in parallel for comparison only
```

**Why keep the old one around at all?** So the team can compare alert volume,
explanation quality, and stability between old and new before fully retiring
the old path — a real migration discipline, not just deleting working code.

#### 4a. The legacy/shadow detector: DTAA + drain3 + Isolation Forest

Lives in `DetectionSample/`. This is a **log-template anomaly detector**, not
a behavioral-baseline model:

1. `log_producer.py` streams raw log lines (already collected in
   `DetectionSample/sample_logs.csv`) — line format looks like
   `04/13/2011 01:25:14  DTAA/CDZ0056  PC-4052  Disconnect`.
2. `drain3_consumer.py` uses the `drain3` library to mine **templates** out of
   free-text log lines — grouping "Connect on PC-4052" and "Connect on
   PC-4531" into the same template, ignoring the specific PC number.
3. `iforest_detector.py` TF-IDF-vectorizes those templates and runs a
   streaming Isolation Forest over a sliding window, flagging templates that
   are statistically rare.
4. Results land in `anomaly_results.json` (each anomaly: a raw log line, its
   Isolation Forest `decision_function` score, and a friendly label like
   "Data Exfiltration Attempt").
5. `backend/app/ps2_correlation/ps1_adapter.py` reads that file, resolves each
   DTAA username to a canonical `entity_id` (via a small `ps1` crosswalk
   inside `entity_mapping.json`), and converts the *most anomalous* log per
   entity into a `RiskAssessment` (`domain=ps1_behavioral`,
   `source=dtaa_legacy`). The Isolation Forest's raw
   `decision_function` (negative = more anomalous) is squashed into a 0–1
   score with a plain logistic curve (`normalize_score`) — a **demo
   calibration**, not a claim about probability.

**Honest limitation, worth knowing:** this detector flags *rare log
templates*, not semantically meaningful insider behavior. The friendly labels
("Data Exfiltration Attempt") are names *mapped onto* whatever templates
happen to be statistically rare — they are not a true semantic classifier.
That's exactly why the team built a better replacement.

#### 4b. The primary detector: CERT behavioral windows + Isolation Forest

This is the real upgrade, and the bulk of PS1's engineering. It's a multi-step
pipeline, each step its own script, each with its own tests:

**Step 1 — Clean, validated raw data.**
`ml/data_pipeline/prepare_cert_data.py` reads the CERT CSVs
(`users.csv`, `logon.csv`, `device.csv`, `file.csv`, `email.csv`) in **chunks**
(never loading the whole email file into memory — some CERT releases are
huge), validates them (unique event IDs, parseable timestamps, every email
sender actually exists in `users.csv`, consistent user/PC IDs), and writes out
a clean, partitioned Parquet dataset. Every run produces a **versioned data
manifest** (`data/manifests/ps1_cert_data_manifest.json`) recording exactly
what was validated, so nobody has to guess what data trained a given model.
Population: 4,000 users, ~18.1 million raw activity events.

**Step 2 — Turn raw events into behavioral windows.**
`ml/data_pipeline/cert_behavioral_windows.py` aggregates all of that into
**one row per user, per hour** (a "user-hour window") — because a single
logon event tells you almost nothing; a *pattern* over an hour (or several
hours) is what actually indicates unusual behavior. For each window it
computes features in five groups:
- **Context**: off-hours/weekend flag, role, privilege level, how close the
  user is to their employment end date.
- **Logon**: how many logons, unusual hour, how many distinct PCs, session
  duration.
- **Device**: USB/removable-media connect count and duration, unusual media
  use.
- **File**: opens/writes/copies/deletes, removable-media direction, path
  novelty (did they touch a folder they've never touched before?).
- **Email**: send/view volume, external-recipient ratio, new
  senders/recipients, attachment size — a *separate, optional* feature group
  (see the base vs. email-enhanced split below).

Crucially, **raw identifiers never become model features** — no raw user ID,
PC ID, file path, or email address goes into the model. They're only used to
*derive* things like "is this PC new for this user" or "count of unique
recipients." This matters for two reasons: it keeps the model generalizable
(it can't just memorize "user X is always risky"), and it avoids baking
PII-like raw values into a model artifact.

**Baselines** are the heart of what makes this "behavioral" rather than just
"anomalous right now": each feature is compared against that *same user's*
rolling 30-day history, and separately against their *role peers'* history,
using **robust statistics** (median + MAD/IQR, not mean/stddev, because a
single wild day shouldn't blow out the baseline the way it would with a plain
average). New users get a 7-day cold-start period. A feature that's always
been zero for someone gets a documented minimum "scale floor" so that the
*first* time they do something (say, first-ever file copy) isn't wrongly
treated as "zero deviation" just because the baseline itself was zero.

Two feature sets are built side by side: **base** (60 features: context +
logon + device + file) and **email-enhanced** (100 features: base + 40
email-derived features). This lets the team measure whether adding email
signal actually helps before committing to the bigger, noisier feature set.

**Step 3 — Train and evaluate the model.**
`ml/models/train_cert_behavioral_model.py`. A few important, deliberate
choices here:

- **Unsupervised, on purpose.** There's no "is this person a real insider"
  label used anywhere in training or evaluation. The CERT ground-truth answer
  key (`data/answers/`) is explicitly off-limits for this whole migration —
  not just avoided, but documented as forbidden — because the goal is a model
  that would work in a real deployment where you *don't* have a labeled
  answer key. Using the answer key even just to "check" the model would be
  quietly quietly leaking supervision into an unsupervised system, which
  would misrepresent how well it'd actually perform live.
- **RobustScaler → VarianceThreshold → Isolation Forest**, with a fixed random
  seed (deterministic — same input always gives the same model).
- The Isolation Forest doesn't output a calibrated probability — it outputs
  "how isolated is this point in feature space." That raw number gets
  converted to a **risk percentile** against a held-out validation set
  (`calibrated_risk`, `np.interp` against pre-computed quantile knots): "this
  window is more anomalous than 99.2% of validation windows" — an honest,
  relative statement, explicitly **not** presented as a calibrated
  probability of anything.
- **Explanations** come from the biggest robust-z deviations in that window
  (e.g. "logon_count is 12 standard-robust-deviations above this user's
  normal" or "new workstation used") — the same mechanism that produces the
  score also produces the human-readable reason, satisfying the
  "explainability from creation" principle.
- A chronological 60/20/20 train/validation/test split (never train on the
  future — every feature for a given window is computed only from *prior*
  history).
- The Isolation Forest is compared against a much simpler, fully transparent
  robust-z-score baseline, and is only "promoted" if it's at least as stable
  and reviewable — the team didn't assume the fancier model wins by default.
- The email-enhanced variant was picked as the shadow candidate over base
  because it produced a lower and more stable daily alert rate in testing —
  not because "more features must be better."
- Explicit alert threshold: `ALERT_RISK_THRESHOLD = 0.99` — only the top ~1%
  most anomalous windows get surfaced as an operational alert at all. Below
  that, no PS1 signal is produced for that window.

**Where CERT scoring code lives now (post today's work):**
`ml/models/cert_behavioral_scorer.py` (`CertBehavioralScorer`) is the single
reusable scorer — it loads the trained model bundle once and exposes
`score_window(...)` (one window in, one `RiskAssessment` or `None` out) and
`score_frame(...)` (a whole partition at once, used for offline batch
replay). Both the offline replay CLI (`ml/replay_cert_assessments.py`) and the
new live endpoint (`POST /ingest/behavioral`, §9) call this *same* code —
there is exactly one place that knows how to turn a CERT window into a
score, so a live score and a replayed score for the same window are always
identical.

---

## 5. PS2 — the fraud / transaction engine

PS2's job: look at a transaction and decide how likely it is to be fraud, with
an explanation attached.

**Feature engineering** (`ml/data_pipeline/paysim_features.py`) starts from
raw PaySim rows (`step`, `type`, `amount`, sender/receiver, before/after
balances, the dataset's own `isFraud` label) and derives:
- `error_balance_orig` / `error_balance_dest` — do the before/after account
  balances actually add up correctly? A mismatch is often a strong fraud
  signal.
- `is_merchant_dest` — PaySim's destination-account naming convention
  (`M...` = merchant) tells you if money went to a business or a person.
- Rolling, per-account features over a trailing window — how many
  transactions has this sender made recently, to how many distinct
  destinations, how does this amount compare to their recent average, how
  long since their last transaction.
- `is_transfer_then_cashout` — flags the classic "account-takeover" pattern:
  transfer money out, then immediately cash it out, from the same origin,
  within a short window.

**Model** (`ml/models/train_fraud_model.py`): XGBoost, trained with a
**time-based split** (train on earlier steps, test on later ones — never let
the model see the future). Two versions are shipped:
- **Full model** — includes raw balance columns. PR-AUC ≈ 0.9998 —
  suspiciously close to perfect. The team investigated *why* rather than just
  celebrating the number, and found it's driven by PaySim's own
  balance-reconciliation columns behaving as near-deterministic simulator
  artifacts (not real-world label leakage, but not a realistic signal
  either).
- **Hardened model** — same approach, minus the raw balance columns. PR-AUC ≈
  0.9195 — still high (PaySim's fraud pattern is genuinely easy to spot even
  honestly), but the number the team actually uses for the demo, because it
  doesn't lean on an artifact.

**Scoring and explanation** (`backend/app/ps2_correlation/fraud_detection/fraud_scorer.py`,
`FraudScorer`): loads the trained XGBoost model plus a SHAP `TreeExplainer`
**once**, then for each transaction row:
- Only scores `TRANSFER` and `CASH_OUT` transaction types — the model was
  only ever trained to discriminate fraud within those types (PaySim fraud
  never happens in other types), so scoring anything else would be
  meaningless. `score_row` returns `None` for any other type — an explicit,
  honest "I have no basis to score this," not a silent wrong answer.
- Runs SHAP to get each feature's exact contribution to *this specific
  transaction's* score, and turns the top 3 contributions into plain-English
  `Reason`s (e.g. `"origin balance does not reconcile after the transaction
  (error_balance_orig=0); raises fraud risk"`), weighted by their share of the
  total contribution.
- **Known caveat, worth remembering**: because PaySim's fraud pattern is so
  separable, the model's scores are **bimodal** — they cluster near 0 or near
  1, with almost nothing realistically landing in the middle. A "mid-range"
  score like 0.6 doesn't naturally occur from this model; that's a known,
  documented limitation, not something the live-scoring work changed.

---

## 6. The entity crosswalk — how PS1 and PS2 point at the same person

This is the single most important thing to understand about how the two
worlds connect, and the single biggest honesty caveat in the whole project,
so read this section carefully.

**CERT and PaySim are two completely unrelated public datasets.** CERT's
usernames (`VSC6934`) and PaySim's account IDs (`C1793991913`) share zero real
identities — no person exists in both datasets. There is no way to *discover*
which CERT user "is" which PaySim account, because in reality, they aren't
the same person; these are two separate simulations.

So `data/synthetic/entity_mapping.json` is a **hand-built, labeled synthetic
bridge**: a JSON file listing entities (currently 30), each with an
`entity_id` (e.g. `E027`), and a `source_ids` block mapping that one entity to
a CERT username, a PaySim account name, and some fake telemetry
identifiers (device IDs, IPs). Of those 30, **25 currently carry both a CERT
username and a PaySim account** — meaning 25 entities can, in principle, show
up in both domains and be correlated. (Earlier project notes said "only 3" —
that was true at an earlier point in the project; the mapping has since grown.
Always check the file itself, not old status notes, for the current count.)

`backend/app/shared/entity_mapping.py` (`resolve_entity(raw_id, source)`)
is the runtime lookup: given a raw CERT username or PaySim account, it
returns the canonical `entity_id`, or raises if that raw ID isn't in the
mapping. This is exactly what lets a CERT-based `RiskAssessment` and a
PaySim-based `RiskAssessment` land on the *same* `entity_id`, which is the
only reason the correlation engine (§8) can ever join them.

**On top of the identity bridge, there's also a time bridge.** PaySim doesn't
have real timestamps — it has a `step` counter (simulated hours since the
simulation started). `backend/app/shared/time_mapping.py` fixes **one global
synthetic clock**: step 0 = `2010-01-01T00:00:00Z`, one step = one hour. Every
PS2 assessment is tagged `time_basis="synthetic_step_mapping"` so nobody
mistakes it for a real observed time.

`ml/data_pipeline/scenario_builder.py` uses both bridges together to build the
demo's most convincing evidence: it takes **real** CERT behavioral windows
that scored above the alert threshold, takes each bridged entity's **real**
PaySim transaction with `isFraud=1`, converts both to the shared clock, and
keeps only the pairs that land within the 120-minute correlation window.
Currently that produces **17 qualifying real-anomaly + real-fraud pairs**.
Nothing about the *individual* signals in those 17 pairs is fabricated — the
CERT model really did flag that window, the PaySim transaction really is
labeled fraud — but the *fact that they're the same person, at a
close-together time*, is a synthetic construct, not a discovered real-world
fact. This distinction ("the mechanism is real; the specific link is
constructed") is the honesty line the whole project holds itself to, and it
should never be blurred when talking about the demo.

---

## 7. Assessment IDs and idempotency

Every `RiskAssessment` needs a stable ID so that re-running a replay, or
retrying a network call, doesn't silently create duplicate incidents.
`backend/app/shared/assessment_schema.py` (`stable_assessment_id`) builds a
deterministic UUID5 from `(source, entity_id, event_time, model_version)` — so
scoring the *exact same* window twice always produces the *exact same*
assessment ID, and the storage layer's `INSERT OR IGNORE` on that ID makes
replays a safe no-op instead of a duplicate.

This same file also defines `RiskAssessmentTransport` — the Pydantic
validation layer sitting in front of the `RiskAssessment` dataclass. It
enforces: scores must be finite numbers in `[0, 1]`, every `Reason`'s domain
must match its assessment's overall domain (you can't have a
`ps1_behavioral` assessment quietly containing a `ps2_transaction` reason),
and old snapshots (missing the newer fields) still load correctly with
sensible defaults — so upgrading the contract never breaks previously
committed demo data.

---

## 8. The correlation engine — where the two worlds actually meet

This is the piece that makes the core thesis literally true in code, not just
in the pitch. It lives in `backend/app/ps2_correlation/correlation_engine/`.

### The policy (`config.py`)
A small, explicitly documented set of constants — **operating policy, not a
statistically calibrated model**:
```
window_minutes     = 120   # how close together two signals must be to corroborate
fire_threshold     = 0.5   # a domain "counts" only if its score clears this
agreement_bonus    = 0.3   # score boost per extra corroborating domain
revoke_threshold   = 0.90  # + high corroboration -> revoke
step_up_threshold  = 0.70  # -> step-up auth
throttle_threshold = 0.40  # -> throttle
```
Why 120 minutes? Long enough to cover a realistic "compromise → drain the
account" attack chain and give an analyst room to investigate, short enough
to reject signals that are genuinely days apart and unrelated. The thresholds
retain the project's original prototype policy pending a proper calibration
exercise against labeled outcomes — this is stated plainly rather than
implied to be scientifically tuned.

### Fusing scores (`fuse_scores`, in `engine.py`)
Given one score per domain for an entity:
- If **two or more** domains each cleared the fire threshold, the combined
  score is a weighted average **boosted** by the agreement bonus (more
  corroborating domains = bigger boost, but capped at 1.0), and corroboration
  is set to `"high"`.
- Otherwise (one domain, or none clearing the threshold), the combined score
  is just the weighted average, and corroboration is `"low"`.

`"high"` and `"low"` describe **corroboration** — "did independent domains
agree" — not statistical confidence. That distinction is called out
repeatedly in the code comments on purpose, because it's easy to
mis-communicate this as "we're 90% sure," which is not what it means.

### Deciding what to do about it (`decide_access`)
```
if combined_score >= 0.90 AND corroboration == "high": REVOKE
elif combined_score >= 0.70: STEP_UP_AUTH
elif combined_score >= 0.40: THROTTLE
else: ALLOW
```
The load-bearing detail: **revoke requires both a high score *and*
corroboration.** A single domain screaming a 0.99 score, alone, only earns
step-up authentication — never an automatic revoke. This is the concrete,
testable version of "reduce false positives" — nobody gets locked out because
one noisy detector had a bad day.

### Same-domain evidence never "corroborates" itself
If the same domain fires twice in a window (e.g. two CERT alerts, or CERT
running in both primary and shadow mode), only the *strongest* assessment
from that domain is kept — repeated same-domain evidence sharpens that
domain's evidence, but never counts as a second, independent domain agreeing.
This is exactly why the DTAA/CERT shadow rule in §4 exists: both are
`ps1_behavioral`, so they could never fake a "two domains agree" story on
their own.

### Windowing and persistence (`store.py`, `TemporalCorrelationStore`)
This is the stateful heart of live correlation, backed by SQLite:
- Every incoming assessment is stored, keyed by its stable `assessment_id` —
  a duplicate arrival is a safe no-op.
- **On every new arrival for an entity, that entity's *entire* history is
  re-windowed from scratch** (`_recorrelate_entity`) — assessments are sorted
  by event time and chopped into fixed windows anchored at the earliest event
  in each cluster. This is what correctly handles **out-of-order arrival**: if
  an assessment for 9:00am shows up *after* one for 10:30am has already been
  processed, re-windowing from scratch still produces the same grouping you'd
  get if they'd arrived in order.
- Windows are **fixed and anchored, not a sliding chain** — three events at
  t=0, t=119min, t=238min produce **two** separate windows (0–119, then a new
  one starting at 238), not one big window stretching the whole 238 minutes.
  This stops "transitive" false corroboration where two genuinely unrelated
  events, far apart, would otherwise get chained together through a middle
  event.
- When incidents are re-materialized after a re-window, the store tries to
  **keep the same incident ID** if the new group shares assessments with a
  previously open incident for that entity — so an incident doesn't get a
  brand-new ID every time a new signal quietly extends it.

### Two separate stores, on purpose
- `TemporalCorrelationStore` (above) is the **detection-side ledger** — raw
  assessments plus materialized incidents, the source of truth for
  correlation logic.
- `IncidentStore` (`backend/app/core/incident_store.py`) is the **API-facing
  store** — what the dashboard actually reads. It gets updated by
  *projection*: whenever correlation produces new/updated incidents, they're
  `upsert`-ed into this store. Critically, `upsert` **preserves whatever
  lifecycle status an analyst has already set** (acknowledged, escalated,
  dismissed) even as the underlying evidence keeps changing — so an
  analyst's decision doesn't get silently reset just because one more piece
  of corroborating evidence arrived. Keeping these two concerns in separate
  stores means "what the math says" and "what the analyst has decided about
  it" can never accidentally clobber each other.

### The alert lifecycle (`core/lifecycle.py`)
A small validated state machine:
```
new -> escalated / acknowledged / dismissed
escalated -> acknowledged / dismissed
acknowledged -> escalated / dismissed
dismissed -> (terminal, no further transitions)
```
When an analyst **dismisses** an incident, that entity is added to a
**suppression list** (`IncidentStore.suppressions`) — the concrete mechanism
behind "the system gets quieter as analysts give feedback." Future incidents
for that entity are flagged `suppressed: true` in API responses, though they
still get created and stored (a human can always still see them; they're
just marked as previously dismissed for context, not silently deleted).

---

## 9. Live scoring — the improvement made today

Everything above §9 already ran live in one important sense: pushing an
**already-scored** `RiskAssessment` to `POST /assessments` triggered
*immediate* re-correlation and incident updates, no restart needed — that
part was real before today.

**What was missing:** the actual model inference — turning raw-ish input into
a score — happened in a *separate offline process*
(`ml/replay_cert_assessments.py` for CERT; an offline pipeline for PaySim),
which then handed the API a finished verdict. The server only ever
*correlated* pre-scored evidence; it never *detected* anything itself. That's
what "we start at scored assessment" meant.

**What changed:** two new endpoints make the server run the models itself, in
the same process, on request:

- **`POST /ingest/transaction`** — takes a prepared PaySim-style feature row,
  runs the existing `FraudScorer` live (same SHAP-explained scoring as
  before, just triggered by an HTTP request instead of an offline script),
  and feeds the resulting `RiskAssessment` into the exact same ingestion →
  correlation → incident pipeline as `/assessments`.
- **`POST /ingest/behavioral`** — takes a prepared CERT behavioral window,
  runs the new `CertBehavioralScorer` live, same path onward.

Both reuse everything that already existed — the ingestion service, the
temporal store, the API-key auth, the correlation engine — unchanged. The
*only* new work was: "run the model here, right now, instead of trusting a
number someone already computed elsewhere."

**What's still intentionally offline, and why:** turning a *raw* CERT log
line into a *feature window* requires 30-day rolling baselines per user and
per role — genuinely stateful, multi-day-history computation. Reproducing
that live (so you could post a raw logon event and have the *server* build
the window from scratch) is a much bigger, separate engineering project — see
`docs/RAW_LOG_INGESTION_ARCHITECTURE_EVALUATION.md` for that plan, which was
deliberately *not* pursued yet. Similarly for PaySim's trailing-window
features. So the honest, precise claim is:

> **Live = model inference + correlation + incident decision.** Raw log →
> feature engineering remains an offline batch stage, same as it's always
> been. This is the same split real SOC (security operations center) tooling
> uses — parsing/feature-building is a batch pipeline; detection is the live
> service sitting on top of it.

**The demo this unlocks:** push a real CERT anomalous window for entity
`E027`, then push a transaction for the same entity within the 120-minute
window (`scripts/demo_live_ingest.py` does exactly this, using committed
sample inputs in `data/synthetic/live_demo_*.json`) — and watch the incident
escalate to `confidence: high`, `access_decision: revoke`, live, in one
running process. This was verified end-to-end against a real running server,
not just unit tests. See `docs/LIVE_SCORING.md` for the full write-up.

---

## 10. How assessments actually get into the system — the transports

Two ways for a `RiskAssessment` to arrive, both funneling into the exact same
`AssessmentIngestionService` (`backend/app/core/assessment_ingestion.py`) so
there's only one place that owns validation, deduplication, and
re-correlation logic:

- **HTTP** — `POST /assessments`, guarded by an API key
  (`VAULTWATCH_INGESTION_API_KEY`, checked with a constant-time comparison to
  avoid timing attacks). Accepts a batch (up to 1,000) of assessments in one
  request; returns which were accepted, which were duplicates, which were
  rejected (with validation errors), and which incidents were affected.
- **Kafka** — same assessment schema, topic `vaultwatch.risk-assessments.v1`,
  consumer group `vaultwatch-correlation-v1`, dead-letter topic
  `vaultwatch.risk-assessments.v1.dlq` for permanently invalid messages.
  Offsets are only committed *after* successful persistence (or successful
  DLQ publication), so a crash mid-processing can't silently drop a message.

**Why does Kafka even exist here, given the team's own mentor raised doubts
about it for bank-scale streaming?** Kafka absolutely *can* handle
bank-scale volume, but only with real operational investment (multiple
brokers, partitioning, monitoring) that isn't needed to prove the core idea.
So the design keeps Kafka **optional** — a transport for deployments that
already run a message broker — while REST is the simple, always-available
path. The demo never requires Kafka to be running.

---

## 11. The quantum / PQC module

The problem statements ask for "quantum-safe security" and "quantum risk
monitoring, including harvest-now-decrypt-later (HNDL) indicators." VaultWatch
takes a **deliberately narrower, honest** interpretation of this, stated
explicitly in `CLAUDE.md` principle #3:

> Real-time detection of someone *passively* harvesting encrypted traffic
> today, to decrypt later once quantum computers exist, is not something
> you can observe from outside — there's no signal to detect. Claiming to
> "detect" that in real time would be dishonest. So this module doesn't try.

Instead, it's a **crypto inventory + migration-prioritization tool**
(`backend/app/quantum_module/crypto_inventory/inventory.py`):
- Given a list of systems and what cryptographic algorithm each currently
  uses (from `data/synthetic/crypto_inventory.json` — 12 example bank
  systems, since there's no real dataset for "what crypto does every bank
  system use"), it classifies each algorithm by substring match (`RSA` →
  quantum-vulnerable, `ML-KEM` → already quantum-safe, etc.).
- Scores a **priority** for migrating each system to post-quantum crypto:
  `vulnerability × data sensitivity × how long the data must stay
  confidential`. A system holding restricted, long-retention data on RSA
  scores far higher priority than a public, short-lived AES-256 system.
- Flags **HNDL exposure** specifically: vulnerable algorithm + confidential-
  or-restricted data + 5+ years of required confidentiality — the classic
  "an attacker harvesting this ciphertext today would still be able to
  decrypt it once quantum computers arrive" combination.
- Recommends the actual NIST-standardized replacement (ML-KEM/Kyber for key
  exchange, ML-DSA/Dilithium for signatures).

Separately, `backend/app/quantum_module/pqc_utils/pqc.py` wraps real
NIST-standardized post-quantum algorithms (`kyber-py` for ML-KEM,
`dilithium-py` for ML-DSA) to actually sign records and establish keys. These
are correct, working implementations of the real standards — but pure-Python
*reference* implementations, not constant-time or production-hardened, and
(worth being upfront about) **nothing else in the codebase currently calls
them.** They're a working, tested capability sitting unused, rather than
wired into, say, signing incident audit records — a clear, honest gap if
someone asks "so is anything actually protected by post-quantum crypto right
now."

---

## 12. How data actually moves, end to end

Two flows exist side by side. Both produce identical `RiskAssessment` /
`UnifiedIncident` shapes; they differ only in *how* the assessment gets
created.

**Offline/demo flow (the original, still used for the committed 5-incident
demo):**
```
CERT CSVs / PaySim CSV
   -> offline feature-engineering scripts (ml/data_pipeline/)
   -> offline model training (ml/models/train_*.py)
   -> offline scoring (ml/replay_cert_assessments.py / build_demo_incidents)
   -> committed JSON snapshots (data/synthetic/*_demo_assessments.json)
   -> loaded into TemporalCorrelationStore at API startup
   -> materialized UnifiedIncidents
   -> IncidentStore (SQLite) -> GET /incidents -> dashboard
```

**Live-injection flow (today's addition):**
```
A prepared feature row/window (from a script, a test, or eventually a
real upstream service)
   -> POST /ingest/transaction  or  POST /ingest/behavioral
   -> model runs IN-PROCESS (FraudScorer / CertBehavioralScorer)
   -> RiskAssessment produced
   -> AssessmentIngestionService (same code the HTTP/Kafka /assessments
      path uses)
   -> TemporalCorrelationStore.ingest() -> re-windows that entity's history
   -> UnifiedIncident(s) produced/updated
   -> projected into IncidentStore (preserving any analyst lifecycle state)
   -> immediately visible via GET /incidents -- no restart, no batch job
```

Notice both flows converge on the exact same correlation/incident machinery —
the only thing that changed over the project's life is *how early* the "live"
boundary starts. It began at "already-scored assessment ingestion + live
correlation," and now starts one step earlier, at "unscored input +
in-process scoring + live correlation."

---

## 13. Running and testing it (backend only)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r backend/requirements.txt
python3 -m uvicorn backend.app.main:app --port 8000
```

Health check: `curl localhost:8000/health` → `{"status":"ok","incidents":N}`.

Full test suite:
```bash
python3 -m pytest backend/tests ml/tests -q
```
131 tests, covering: entity resolution, PaySim features, both fraud models,
the fraud scorer, both PS1 providers (CERT + DTAA), the assessment schema and
its validation rules, the correlation engine (including out-of-order and
same-domain-doesn't-corroborate cases), the incident store and lifecycle,
HTTP and Kafka ingestion (including cross-transport deduplication), the
quantum module, and — as of today — the two live-scoring endpoints, including
an end-to-end test that pushes a behavioral signal and a transaction signal
for the same entity and asserts the resulting incident is a high-confidence
revoke.

Live demo:
```bash
rm -f data/incidents.db
VAULTWATCH_INGESTION_API_KEY=<key> python3 -m uvicorn backend.app.main:app --port 8000 &
VAULTWATCH_INGESTION_API_KEY=<key> python3 scripts/demo_live_ingest.py
```

---

## 14. Glossary — words this codebase uses precisely

- **Score** — a 0–1 number from one detector. Higher = riskier. Not a
  probability unless explicitly stated (PS1's is an empirical percentile;
  PS2's is closer to a real probability but the underlying model is bimodal).
- **Domain** — which world a signal came from: `ps1_behavioral`,
  `ps2_transaction`, or (reserved, unbuilt) `ps2_telemetry`, or `quantum`.
- **Corroboration** (`high`/`low`) — did **two or more independent domains**
  fire for the same entity in the same time window? This is a count-based
  rule, **not** a statistical confidence interval. Never say "90%
  confident" when what's meant is "two domains agreed."
- **Combined score** — the fused number after `fuse_scores()`, potentially
  boosted if corroborating.
- **Access decision** — the actual output that matters: `allow` / `throttle`
  / `step_up_auth` / `revoke`.
- **Entity** — the one canonical identity a person/service/script has across
  every domain in this system.
- **Assessment** vs **Incident** — an assessment is one detector's one
  opinion; an incident is what the correlation engine builds by fusing one
  or more assessments for one entity in one time window.
- **Constructed / synthetic** (as used throughout this doc and the code
  comments) — a specific, labeled thing the team built by hand for the demo
  (an entity link, a paired timestamp, a made-up crypto inventory), as
  opposed to something that came directly out of a real dataset or a real
  model's own output.

---

## 15. Known gaps, worth stating plainly

Kept here so this stays the up-to-date, single source of truth for "what's
real vs. not yet built" (an earlier such document existed and was
intentionally removed; the substance is preserved here):

- **No real PAM (privileged access management) module.** The
  `ps1_insider_threat/pam/` package exists as an empty placeholder.
- **No dedicated "intent/context-aware" scoring module.** The
  `risk_scoring/` package is also an empty placeholder — what actually ships
  is CERT's statistical behavioral-deviation model, which is powerful but not
  the same thing as "does this access have a legible business justification."
- **HR-event signal is a dead field.** `Entity.hr_flag` exists in the schema
  and the data files, but no scoring code reads it yet.
- **PQC utilities are unwired** — real, tested crypto code with no caller
  anywhere else in the system (§11).
- **Only two correlation domains exist** — `ps2_telemetry` (the "cyber
  telemetry" the PS2 title names) was never built; only behavioral +
  transaction fusion works today.
- **Correlation thresholds are policy, not calibrated** against any labeled
  outcome set — stated openly in `config.py` itself.
- **The entity crosswalk and cross-dataset timing remain synthetic** — real
  mechanism, constructed specific links (§6). This is the one caveat every
  future contributor must keep visible; don't let a future demo or doc
  present these links as discovered rather than built.
- **Raw-log-level live ingestion** (posting a raw logon/transaction line and
  having the *server* build the feature window from scratch) remains future
  work — see `docs/RAW_LOG_INGESTION_ARCHITECTURE_EVALUATION.md`.
