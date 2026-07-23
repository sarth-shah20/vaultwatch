# Global-clock CERT + PaySim Demo Scenarios

Source of truth: `data/synthetic/demo_scenarios.json`. Regenerate with:

```bash
.venv/bin/python3 -m ml.data_pipeline.scenario_builder
```


## Correlation-engine replay

`build_demo_incidents()` feeds committed CERT and PaySim assessment artifacts into
`TemporalCorrelationStore` (SQLite) and returns materialized incidents. This is
engine execution, not scenario-builder discovery. `CERT:CET3786` replay produces
one incident with `ps1_behavioral` + `ps2_transaction`, `high` corroboration, and
`revoke`; its two event times remain 57.533 minutes apart. Incident IDs are UUID-backed
and allocated by store, so consumers must use returned ID rather than derive it from entity.

## Timing and identity honesty

PaySim has a relative simulated `step`, not an observed transaction timestamp.
VaultWatch uses one fixed global mapping everywhere: **step 0 =
2010-01-01T00:00:00Z; each step adds one hour**. Every PS2 assessment carries
`time_basis: "synthetic_step_mapping"`; this is a synthetic clock, not a claim
about real banking event time.

CERT users and PaySim accounts also have no natural cross-dataset identity.
`cert_paysim_global_demo_crosswalk.json` records a deterministic synthetic bridge
that is created before and independently of event times, risk scores, labels,
or transaction amounts. It must not be presented as a real identity resolution.

## Selection rule

`scenario_builder.py` scores real CERT behavioral windows using the
email-enhanced Isolation Forest, keeps windows at the operational alert threshold
(`risk >= 0.99`), pairs them with each bridged account's earliest real PaySim
`isFraud=1` transaction, and retains only pairs within 120 minutes under the
single global clock. It does not set per-scenario timestamps or select pairs to
fit a desired narrative.

Current generated artifact contains 17 qualifying pairs. Each includes the
CERT model score/explanation, real PaySim transaction type/amount, globally
derived PS2 timestamp, and observed gap. These are synthetic cross-dataset
correlations suitable for integration testing and demo flow—not evidence that
CERT users own PaySim accounts or that their source systems shared a clock.
