# Demo Scenarios (PS1 + PS2 bridge)

Three concrete, timed "attack scenarios" that give the correlation engine (Step 6)
a same-entity, same-window pair of signals to join — one **behavioral** (PS1 /
CERT) and one **transactional** (PS2 / PaySim) — for the same person.

**Data honesty (read this first):**
- Every CERT event below is a **real row** from the CMU CERT `logon.csv` (cited by
  its row id). Every PaySim transaction is a **real `isFraud=1` row** for that
  entity's mapped account. **Nothing here is injected** — `demo_scenarios.json`
  reports `injected_cert_events: 0` and `injected_paysim_txns: 0`.
- The **only** curated element is the *cross-dataset time alignment*: CERT uses
  absolute 2010–2011 timestamps, PaySim uses a relative hourly `step` with no
  absolute date. They are independent simulations with no shared clock, so we
  place each real PaySim fraud transaction a plausible number of minutes after the
  real CERT event (`curated_alignment: true`). The events are real; only their
  minutes-apart placement on one timeline is constructed for the demo.
- The correlation thesis: a weekend/off-hours logon *alone* is a soft signal, and
  a large transfer *alone* is a soft signal — but the **same entity firing both
  inside one window** is high-confidence. These scenarios are built to show
  exactly that join.

Source of truth: `data/synthetic/demo_scenarios.json` (regenerate with
`python3 ml/data_pipeline/scenario_builder.py`).

---

## Scenario S1 — E028 · off-hours access → account drained
**Entity:** E028 (finance_analyst) · CERT user `DJA0740` · PaySim account `C686187434`

At **02:43 on 29 Apr 2010**, this finance analyst logs in from `PC-7197`
(real CERT row `{L0K2-C9NC86KG-2123YGZE}`) — well outside their normal
07:00–19:00 weekday pattern. Roughly **37 minutes later**, a **CASH_OUT of
6,188,515** posts on their mapped account — a real PaySim `isFraud=1`
transaction that drains the account.

**Why it correlates:** a genuine off-hours privileged logon immediately followed
by a full-balance cash-out. Either signal could be noise; together, for one
identity in one window, it's a textbook insider-drain.

## Scenario S2 — E027 · weekend access → large transfer
**Entity:** E027 (operations_analyst) · CERT user `MBA1797` · PaySim account `C635739031`

On **Saturday 02 Jan 2010, 07:03**, this operations analyst logs in from
`PC-0470` (real CERT row `{P8G9-J4HP25SR-5398XSPY}`) — weekend access, outside
their weekday pattern. About **52 minutes later**, a **TRANSFER of 1,965,786**
(real PaySim `isFraud=1`) moves out of their account.

**Why it correlates:** weekend access on its own is a weak flag, but paired with a
seven-figure fraudulent transfer from the same actor it becomes a credible
"moving money when no one's watching" case.

## Scenario S3 — E029 · weekend access → cash-out
**Entity:** E029 (payments_operator) · CERT user `JPC2507` · PaySim account `C812001868`

On **Saturday 02 Jan 2010, 07:04**, this payments operator logs in from
`PC-0747` (real CERT row `{K1Q3-R3QB95BY-7218BTGO}`). About **44 minutes later**,
a **CASH_OUT of 4,445,514** (real PaySim `isFraud=1`) leaves the account.

**Why it correlates:** same shape as S2 with a cash-out instead of a transfer —
useful for showing the correlation engine handles multiple fraud typologies.

---

## What each scenario hands the correlation engine
For every scenario, the entity resolves to one canonical `entity_id`
(`resolve_entity`), the PS1 side can emit a behavioral `RiskAssessment` (off-hours
/ weekend access), and the PS2 `FraudScorer` emits a transactional
`RiskAssessment` on the real fraud transaction. Step 6 joins them on
`entity_id` within the incident window and raises confidence because two
independent domains agree — the core "reduces false positives" argument.
