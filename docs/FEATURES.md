# Feature List — Build Priority Reference

Legend: `[CORE]` = must build for a working demo. `[STRETCH]` = build if time
permits. `[UNIQUE]` = differentiator from our research, not in either PS verbatim.

Fill in owner + status as the team picks up work.

## PS1 — Privileged Access Misuse & Insider Threat Detection

| # | Feature | Priority | Owner | Status |
|---|---------|----------|-------|--------|
| 1 | Entity-based behavioral baseline engine (human + service accounts) | CORE | | |
| 2 | Intent/context-aware access risk scoring | CORE [UNIQUE] | | |
| 3 | Real-time privileged session monitoring & alerting | CORE | | |
| 4 | Risk-based / adaptive access control engine | CORE | | |
| 5 | PAM core (privileged account inventory, least privilege) | CORE | | |
| 6 | Critical admin system shielding (extra scrutiny tier) | STRETCH | | |
| 7 | HR-event-aware risk signal | STRETCH [UNIQUE] | | |
| 8 | Offboarding / access lifecycle hygiene check | STRETCH [UNIQUE] | | |
| 9 | QPC for credentials & audit artifacts | CORE | | |
| 10 | Behavioral biometric signal (keystroke timing demo) | STRETCH [UNIQUE] | | |

## PS2 — AI-Driven Correlation of Telemetry & Transactional Behaviour

| # | Feature | Priority | Owner | Status |
|---|---------|----------|-------|--------|
| 1 | Cross-domain correlation engine | CORE | | |
| 2 | Proactive cyber threat detection | CORE | | |
| 3 | Fraud pattern detection module (PaySim-based) | CORE | | |
| 4 | Quantum risk — crypto exposure & prioritization module | CORE [UNIQUE reframe] | | |
| 5 | Alert fusion & false-positive reduction layer | CORE | | |
| 6 | Explainable alert / case generation | CORE | | |
| 7 | Alert lifecycle management (new -> escalated -> dismissed w/ feedback) | STRETCH [UNIQUE] | | |
| 8 | Unified risk score / incident view (PS1+PS2 bridge) | CORE | | |

## Suggested build order (rough)

1. Day 1: shared entity model + schemas agreed by whole team; datasets downloaded;
   synthetic bridge-layer design sketched.
2. Day 1-2: PS1 baseline engine + basic risk scoring running on CERT data.
3. Day 2-3: PaySim fraud model running standalone; synthetic telemetry generator
   producing 2-3 injected attack scenarios.
4. Day 3-4: Correlation engine joining PS1 + PS2 signals into unified incident
   view; explainability layer attached.
5. Day 4-5: Quantum module (crypto inventory + PQC utils wired into credential/
   audit storage); frontend dashboard wired to real backend endpoints.
6. Day 5-6: Polish, demo script, stretch goals if time allows.
7. Day 6-7: Buffer / rehearsal — do not schedule new features here.
