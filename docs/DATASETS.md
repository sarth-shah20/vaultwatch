# Datasets

No single public dataset covers PS1 + PS2 together. Plan: two real/synthetic
public datasets as the backbone, plus a synthetic "bridge" layer we generate
ourselves to connect them.

## 1. CMU CERT Insider Threat Dataset (for PS1)

- Source: CMU Software Engineering Institute (CERT Division), with ExactData LLC,
  under DARPA I2O sponsorship.
- What it is: synthetic logs of employee computer activity across a simulated
  organization, over ~18 months, with a small number of labeled "insider" /
  malicious actors mixed in among thousands of normal employees.
- Files typically included: `logon.csv`, `email.csv`, `http.csv`, `file.csv`,
  `device.csv` (thumb drive connect/disconnect), and in some releases
  `psychometric.csv`.
- Versions: r4.2 (smaller, ~10GB-class, easier to work with for a hackathon),
  r6.2 (larger, ~22GB, more scenarios/insiders — 3995 benign employees + 5 insiders
  in some published splits).
- Where to get it:
  - CMU Figshare / KiltHub: https://kilthub.cmu.edu/articles/dataset/Insider_Threat_Test_Dataset/12841247
  - CMU SEI page: https://www.sei.cmu.edu/library/insider-threat-test-dataset/
  - Also mirrored/discussed on Kaggle (search "CERT Insider Threat")
- **Recommendation: start with r4.2.** It's smaller and faster to iterate on in a
  week-long hackathon; only move to r6.2 if you have time and want richer scenarios.
- Use for: baseline behavioral engine (`backend/app/ps1_insider_threat/baseline`),
  training/testing anomaly + intent-context risk scoring.

## 2. PaySim (for PS2 — transaction fraud)

- Source: Kaggle, originally derived from real mobile money transaction logs
  (anonymized), simulating a service used in 14+ countries.
- Size: ~6.3 million transactions over 744 simulated hourly steps (30 days).
- Key fields: `step` (hour), `type` (CASH-IN / CASH-OUT / DEBIT / PAYMENT / TRANSFER),
  `amount`, `nameOrig`, `oldbalanceOrg`, `newbalanceOrig`, `nameDest`,
  `oldbalanceDest`, `newbalanceDest`, `isFraud`, `isFlaggedFraud`.
- Fraud pattern modeled: agents taking control of accounts and draining funds via
  transfer + cash-out — a good realistic pattern to correlate against security
  telemetry (e.g. a compromised-session signal preceding a drain-and-cash-out).
- Where to get it: Kaggle — search "PaySim1" or "Fraud Detection Analysis" (Kaggle
  competition mirror also exists).
- Alternative/supplementary options if needed: IEEE-CIS Fraud Detection dataset
  (~590K e-commerce transactions, richer feature set, real Vesta Corp data via
  Kaggle competition), or the ULB European Credit Card Fraud dataset (smaller,
  ~285K transactions, heavily PCA-anonymized).
- Use for: `backend/app/ps2_correlation/fraud_detection` model training/testing.

## 3. Synthetic security telemetry (bridge layer — build this ourselves)

There is no public dataset joining privileged-user behavior + security telemetry +
bank transactions. To make PS2's "correlation" story demoable, generate a synthetic
telemetry stream (logins, device/IP metadata, endpoint alerts, auth failures) keyed
to the **same synthetic entity IDs** used across CERT and PaySim data, so the
correlation engine has a real join key to work with.

Suggested approach:
1. Pick a small set of "demo entities" (e.g. 20-50 synthetic users/accounts).
2. For each, generate a plausible telemetry timeline (normal logins + a few
   injected "attack scenario" timelines — e.g. phishing alert -> odd login -> large
   transfer from PaySim-style data for that same entity).
3. Store under `data/synthetic/` — see `ml/data_pipeline/` for generation scripts.

This bridge layer is what actually sells the PS2 "correlation" story in the demo —
budget real time for building 2-3 convincing injected attack scenarios rather than
trying to make the correlation "generic" across arbitrary data.

## 4. Quantum / crypto-inventory module — no dataset needed

This module works over a small **synthetic system/data-flow inventory** you define
yourselves (e.g. a spreadsheet or JSON listing systems, what crypto they currently
use, data sensitivity, retention period). It's a rules/heuristics + prioritization
tool, not something you train a model on. See `backend/app/quantum_module/crypto_inventory/`.
