# Architecture Overview

## Core thesis

Intent/context-aware access risk (not just anomaly-based), correlated across
privileged-session behavior + transaction + telemetry signals, with quantum-safe
crypto as a first-class concern.

## Three components, one shared spine

```
                        ┌─────────────────────────┐
                        │   Shared Entity Model     │
                        │ (human / service account  │
                        │  / script — one schema)   │
                        └────────────┬─────────────┘
                                     │
        ┌────────────────────────────┼────────────────────────────┐
        │                            │                             │
┌───────▼────────┐         ┌─────────▼──────────┐        ┌─────────▼─────────┐
│  PS1 Engine     │         │  PS2 Correlation    │        │  Quantum Module    │
│                 │         │  Layer              │        │                    │
│ - Baseline      │────────▶│ - Fraud detection   │        │ - Crypto inventory │
│ - Intent/context│  signal │ - Cross-domain join  │        │ - PQC migration    │
│   risk scoring  │  feed   │   (security telemetry│        │   priority scoring│
│ - Risk-based    │         │   + transactions)    │        │ - PQC utils for    │
│   access control│         │ - Alert fusion /      │        │   credentials/logs │
│ - PAM core      │         │   false-positive       │       │                    │
│                 │         │   reduction            │       │                    │
└───────┬────────┘         │ - Explainability      │        └────────────────────┘
        │                   └─────────┬──────────┘
        │                             │
        └──────────────┬──────────────┘
                        │
              ┌─────────▼──────────┐
              │  Unified Incident   │
              │  / Risk Score View  │
              │  (the PS1+PS2       │
              │   bridge object)    │
              └────────────────────┘
```

## Component responsibilities

### 1. PS1 — Insider Threat / Privileged Access Engine
- **Baseline** (`ps1_insider_threat/baseline/`): builds per-entity behavioral
  profiles from CERT-derived data (login times, systems touched, data volumes,
  command patterns). Entity = human OR service account/script.
- **Risk scoring** (`ps1_insider_threat/risk_scoring/`): the key differentiator —
  scores access based on whether it has a legible business justification given
  the entity's current context, not just statistical deviation from history.
  Also incorporates HR-event signals (termination/disciplinary flags) as a
  risk multiplier.
- **PAM** (`ps1_insider_threat/pam/`): privileged account inventory, session
  monitoring, least-privilege / just-in-time elevation, offboarding hygiene checks.

### 2. PS2 — Correlation & Explainability Layer
- **Fraud detection** (`ps2_correlation/fraud_detection/`): PaySim-trained model(s)
  detecting known fraud patterns (drain-and-cash-out, velocity anomalies, etc.)
- **Correlation engine** (`ps2_correlation/correlation_engine/`): joins PS1 signals
  + synthetic security telemetry + transaction signals via shared entity IDs;
  produces a fused, higher-confidence risk assessment when multiple domains agree.
- **Explainability** (`ps2_correlation/explainability/`): every alert/incident
  carries structured reasons (which signals fired, from which domain, what weight)
  from the moment it's created.

### 3. Quantum Module
- **Crypto inventory** (`quantum_module/crypto_inventory/`): catalogs which
  systems/data flows use legacy (RSA/ECC) crypto, scores by data sensitivity x
  retention period, produces a prioritized PQC-migration list. This is the honest
  answer to "quantum risk monitoring" — NOT real-time detection of harvesting.
- **PQC utils** (`quantum_module/pqc_utils/`): wraps NIST-standardized PQC
  algorithms (ML-KEM for key exchange, ML-DSA for signatures) to actually encrypt/
  sign credentials and audit logs produced by the PS1 engine.

## The bridge: Unified Incident view

A single correlated "incident" object that can combine a PS1-side signal
(privileged session anomaly / unjustified access) with a PS2-side signal
(transaction/telemetry anomaly) into one explained, risk-scored case. This is the
concrete artifact that demonstrates the PS1+PS2 synergy in the demo — build this
early so both halves of the team have something to integrate against.

## What NOT to build (explicit non-goals)

- Real-time detection of passive HNDL/quantum harvesting — not feasible, don't
  attempt it; the crypto-inventory reframe is the intentional answer here.
- A generic, fully configurable rules engine — pick 2-3 concrete demo scenarios
  and build those well rather than a general-purpose platform.
- Full identity/HR system integration — mock the HR-event signal with a simple
  flag/webhook rather than building real HR system integration.
