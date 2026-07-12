# CLAUDE.md

Guidance for Claude Code when working in this repository.

## Project context

Hackathon project (FinSpark, Bank of Maharashtra) combining two problem statements
into one system:
- **PS1**: Privileged access misuse & insider threat detection
- **PS2**: AI-driven correlation of cybersecurity telemetry & transactional behaviour

Full details in `docs/ARCHITECTURE.md` and `docs/FEATURES.md` — read these before
making structural changes.

## Core design principles (do not violate without asking)

1. **Shared entity model first.** All modules (PS1 behavioral engine, PS2 fraud
   detection, correlation engine) must reference the same `Entity` concept defined
   in `backend/app/shared/` — an entity can be a human user, a service account, or
   an automation/script. Don't create parallel/duplicate user models per module.
2. **Every alert carries structured explainability data from creation** — not
   generated after the fact. When writing code that raises an alert/flags risk,
   always attach a `reasons: list[Reason]` style structure (signal name, weight,
   raw value) — never just a bare score.
3. **The quantum module does NOT try to "detect" harvest-now-decrypt-later attacks
   in real time.** It is a crypto-inventory + prioritization tool (what data/systems
   use legacy crypto, how sensitive, how long-lived, ranked by migration priority).
   Do not write code that claims to detect passive quantum harvesting — this is
   intentionally out of scope and was a deliberate team decision.
4. **Risk-based access control produces a decision, not just a score** — allow /
   step-up-auth / throttle / revoke. When implementing risk scoring, always wire it
   to an actual access-control decision function, not a dashboard number alone.

## Tech stack (fill in once decided)

- Backend: [Django REST / FastAPI — confirm with team]
- Frontend: React + [Vite/Next]
- ML: Python (pandas, scikit-learn, and/or PyTorch depending on model choice)
- DB: [Postgres / SQLite for prototype]

## Commands

Fill these in once each part of the stack is scaffolded:
- Backend run: `TBD`
- Backend tests: `TBD`
- Frontend dev server: `TBD`
- ML pipeline run: `TBD`

## Workflow preferences

- Small, testable changes; commit frequently with clear messages.
- Each of PS1 / PS2 / quantum_module should be independently runnable/testable
  against the shared schemas — avoid tight coupling that blocks parallel work.
- When in doubt about scope (e.g. "should this be real-time or batch"), check
  `docs/FEATURES.md` for what's marked as core/must-build vs. stretch goal.
