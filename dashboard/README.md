# VaultWatch Analyst Dashboard (Streamlit)

A thin analyst console that consumes the Correlation API (`backend/app/main.py`)
and renders correlated `UnifiedIncident` cases.

## What it shows
- Header metrics: total incidents, revoke decisions, high-confidence count, suppressed entities.
- Bar chart of incidents by access decision.
- Per-incident **case file**: combined score, confidence, status, contributing
  domains, and the reasons grouped by domain (PS1 behavioral vs PS2 transactional).
- **Analyst actions** — Acknowledge / Escalate / Dismiss (with reason) — which POST
  to the API, drive the alert lifecycle, and (on dismiss) suppress the entity.

## Run
From the repo root, in two terminals:
```
# 1) API
uvicorn backend.app.main:app --reload

# 2) Dashboard  (VAULTWATCH_API overrides the API URL if not localhost:8000)
streamlit run dashboard/app.py
```

## Layout
- `client.py` — thin, testable API client + data-shaping helpers (`summarize`,
  `reasons_by_domain`). An httpx client can be injected for tests.
- `app.py` — the Streamlit UI (kept thin; logic lives in `client.py`).

Install: `pip install -r dashboard/requirements.txt`.
