# PS1 ↔ PS2 Integration

How the teammate's PS1 pipeline plugs into our PS2 / correlation layer.

## The two sides
- **PS1 (teammate):** drain3 + Isolation Forest over the DTAA security-log dataset
  (`DetectionSample/`, branch `ps1`), emitting `anomaly_results.json` (per anomaly:
  `log`, `score` = Isolation-Forest `decision_function`, `reason`). Runs on Kafka
  internally — irrelevant to us; we integrate on its **output**.
- **PS2 (us):** `FraudScorer` over PaySim, emitting the shared `RiskAssessment`.

## The problem
The two datasets share **no** entity key — PS1's DTAA usernames (`RET4173`,
`VSC6934`, …) and our mapped CERT usernames are disjoint (verified: 0 overlap).
And no dataset naturally links any behavioral identity to a PaySim account.

## The bridge (deliberate + labeled)
`entity_mapping.json` was always a synthetic bridge (entity ↔ CERT ↔ PaySim). We
extend it with a `ps1` field on the three demo entities, crosswalking each to a
DTAA user the PS1 detector reliably flags:

| entity | ps1_user | headline PS1 anomaly | PaySim fraud |
|---|---|---|---|
| E027 | VSC6934 | Data Exfiltration Attempt | TRANSFER 1,965,786 |
| E028 | RET4173 | Multiple Failed Login Attempts | CASH_OUT 6,188,515 |
| E029 | DGX1939 | Suspicious Login from Foreign IP | CASH_OUT 4,445,514 |

This crosswalk is the only synthetic identity link, documented as such.

## The adapter
`backend/app/ps2_correlation/ps1_adapter.py` → `load_ps1_assessments()`:
1. reads `ps1_anomaly_results.json`,
2. resolves each DTAA `USER` → `entity_id` via the `ps1` crosswalk,
3. normalizes the Isolation-Forest `decision_function` (more negative = more
   anomalous) to a 0–1 risk (`normalize_score`, a documented demo calibration),
4. emits a `RiskAssessment(domain="ps1_behavioral")` per entity (strongest anomaly
   as the primary `Reason`, other flagged activities as supporting reasons).

## Why not just feed our CERT logs into their detector?
We tried it. Their model TF-IDFs the log **text**, which is weak on plain
Logon/Logoff (it flags unique-ID noise, not behavior). Their detector shines on
the **DTAA** data because activities like "Data Exfiltration Attempt" are rare,
meaningful tokens — so we use their pipeline on the data it was built for, and
bridge identities via the crosswalk instead.

## Swapping in the live pipeline
When the teammate's pipeline runs live, point the adapter's `anomalies_path` at
the file it writes. Nothing else changes — the correlation engine only ever sees
`RiskAssessment` objects.

## Honesty summary
Real: the PS1 anomalies (their model on their data) and the PaySim fraud
transactions. Deliberate/labeled demo constructs: the entity↔DTAA-user crosswalk
and the cross-dataset time alignment.
