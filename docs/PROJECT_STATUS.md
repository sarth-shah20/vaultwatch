# VaultWatch — Project Status (PS2 track + PS1 integration)

_FinSpark Hackathon · Bank of Maharashtra · repo: sarth-shah20/vaultwatch · 16 Jul 2026_

## 1. What VaultWatch is
Unified system across two problem statements:
- **PS1** — Privileged Access Misuse & Insider-Threat Detection (behavioral).
- **PS2** — AI-driven correlation of cybersecurity telemetry & transactional behaviour.

**Thesis:** a behavioral red flag alone or a suspicious transaction alone is a soft signal; the **same entity firing both in one window** is high-confidence. Everything speaks one shared contract: `RiskAssessment` → `UnifiedIncident` (`backend/app/shared/entities.py`).

## 2. Data
| Dataset | Use | Status |
|---|---|---|
| PaySim (`ealaxi/paysim1`) | PS2 fraud (6.36M txns, 8,213 fraud) | Public, downloaded |
| CMU CERT (`mrajaxnp/...`) | our behavioral identities | Downloaded |
| DTAA logs (teammate `DetectionSample/`) | PS1 detector input | On `ps1` branch |

Raw datasets gitignored; trained fraud models committed for handoff.

## 3. Pull requests
| PR | Title | Status |
|---|---|---|
| #1 | Fix entity resolution | Merged |
| #2/#3 | Explainable XGBoost fraud model + scorer (+ artifacts) | Merged |
| #4 | Curated PS1+PS2 demo scenarios | Merged |
| #5 | Integrate PS1 via crosswalk + adapter; rebuild scenarios | Open |
| #6 | Step 6 correlation engine (+ this status doc) | Open (stacked on #5) |

## 4. PS2 fraud model
Two models on real PaySim (TRANSFER+CASH_OUT, time-based split, SHAP reasons):
- **Full / primary** — PR-AUC **0.9998**.
- **Hardened / production-realistic** — PR-AUC **0.9195** (drops raw+destination balances).
- We audited the near-perfect score: driven by PaySim balance-column *artifacts*, not label leakage (`ml/evaluation/leakage_analysis.md`). `FraudScorer` emits `RiskAssessment` with SHAP reasons; returns `None` for non-TRANSFER/CASH_OUT types.

## 5. PS1 integration
- PS1 (teammate: drain3 + Isolation Forest on DTAA data) and our data share **no username** (0 overlap). Bridge = a labeled `ps1` crosswalk in `entity_mapping.json` on 3 demo entities → DTAA users the detector reliably flags (E027←VSC6934 Data-Exfil, E028←RET4173 Failed-Logins, E029←DGX1939 Foreign-IP).
- `ps1_adapter.py`: their `anomaly_results.json` → shared `RiskAssessment` (`domain="ps1_behavioral"`, score normalized 0–1).
- `demo_scenarios.json`: real PS1 anomaly + real `isFraud=1` PaySim txn per entity, **0 injected**.

## 6. Correlation engine (Step 6)
`backend/app/ps2_correlation/correlation_engine/` fuses per-domain `RiskAssessment`s → `UnifiedIncident` by entity:
- Corroboration (≥2 domains) **boosts** the score (graduated, not saturated) and sets `confidence="high"`.
- A lone signal keeps its score but stays `confidence="low"` → **step-up verification, not auto-revoke** (this is the "correlation reduces false positives" lever).
- `decide_access`: revoke requires high score **and** high confidence.

Demo (`build_demo_incidents`): all 3 entities → high-confidence escalated `REVOKE`, with **differentiated** scores (0.984 / 0.978 / 0.948) and both behavioral + transactional reasons attached. FP check: lone fraud score 0.95 → step-up; corroborated → revoke.

## 7. Tests
`pytest backend/tests ml/tests` → **65 passing** (entity resolution, PaySim features, fraud model, fraud scorer, PS1 adapter, demo scenarios, correlation engine).

## 8. Honesty ledger
- **Real:** PaySim fraud txns; CERT/DTAA events; PS1 Isolation-Forest anomalies; PS2 fraud scores + SHAP reasons.
- **Deliberate, labeled demo constructs:** the entity↔identity↔PaySim mapping; the entity↔DTAA-user crosswalk; the cross-dataset time alignment.
- We found & documented the PaySim artifact issue ourselves and built the hardened model in response.

## 9. What's left
- Alert lifecycle + analyst feedback loop.
- API endpoint serving `UnifiedIncident` + minimal incident dashboard.
- Fold teammate's `DetectionSample/` into a real-system layout (coordinate with teammate; our integration consumes its output so is unaffected).
- Optional: quantum crypto-inventory module.
