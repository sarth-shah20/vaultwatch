# Demo Scenarios (PS1 + PS2 bridge)

Three concrete, timed "attack scenarios" that give the correlation engine (Step 6)
a same-entity pair of signals to join — one **behavioral** (PS1 / Isolation-Forest
on the DTAA security-log dataset) and one **transactional** (PS2 / PaySim fraud) —
for the same person, inside one window.

**Data honesty (read first):**
- Each PS1 event is a **real anomaly** flagged by the teammate's Isolation Forest
  (`ps1_anomaly_results.json`); each PaySim transaction is a **real `isFraud=1`**
  row. `demo_scenarios.json` reports `injected: 0`.
- Two elements are **deliberate, labeled demo constructs**: (1) the entity ↔
  DTAA-user **crosswalk** (`ps1` field in `entity_mapping.json`) — no dataset
  naturally links a behavioral identity to a PaySim account; and (2) the
  cross-dataset **time alignment** (`curated_alignment: true`) — PS1 uses absolute
  dates, PaySim a relative hourly step, so we place the real fraud a plausible gap
  after the real anomaly.
- The correlation thesis: a behavioral red flag alone or a large transfer alone is
  a soft signal; the **same entity firing both in one window** is high-confidence.

Source of truth: `data/synthetic/demo_scenarios.json`
(regenerate: `python3 ml/data_pipeline/scenario_builder.py`).

---

## S1 — E028 · repeated failed logins → account drained
**Entity:** E028 (finance_analyst) · PS1 user `RET4173` · PaySim account `C686187434`

PS1's Isolation Forest flags **Multiple Failed Login Attempts** for this actor
(risk 0.85). ~37 minutes later a **CASH_OUT of 6,188,515** — a real PaySim
`isFraud=1` — drains the account. Brute-forced access immediately followed by a
full-balance cash-out.

## S2 — E027 · data exfiltration → large transfer
**Entity:** E027 (operations_analyst) · PS1 user `VSC6934` · PaySim account `C635739031`

PS1 flags a **Data Exfiltration Attempt** at 22:12 (off-hours), its strongest
anomaly (risk 0.96). ~52 minutes later a **TRANSFER of 1,965,786** (real PaySim
`isFraud=1`) leaves the account. Exfiltration staged, then value moved out — the
headline insider-threat narrative.

## S3 — E029 · foreign-IP login → cash-out
**Entity:** E029 (payments_operator) · PS1 user `DGX1939` · PaySim account `C812001868`

PS1 flags a **Suspicious Login from Foreign IP** at 21:42 (risk 0.94). ~44 minutes
later a **CASH_OUT of 4,445,514** (real PaySim `isFraud=1`). Compromised-session
pattern feeding a fraudulent cash-out.

---

## What each scenario hands the correlation engine
Each entity resolves to one canonical `entity_id`. The PS1 adapter
(`ps1_adapter.load_ps1_assessments`) emits a behavioral `RiskAssessment`
(`domain="ps1_behavioral"`) from the real anomaly; the PS2 `FraudScorer` emits a
transactional `RiskAssessment` on the real fraud transaction. Step 6 joins them on
`entity_id` within the window and raises confidence because two independent domains
agree — the "reduces false positives" argument, made concrete.
