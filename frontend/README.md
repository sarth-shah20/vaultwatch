# VaultWatch Frontend

React + Tailwind single-page dashboard for the VaultWatch correlation API.

## Run locally

Prereqs: Node 18+ and the backend dependencies installed (`pip install -r requirements.txt` at repo root).

**Terminal 1 — backend (from repo root):**

```bash
python3 -m uvicorn backend.app.main:app --port 8000
```

**Terminal 2 — frontend (from this directory):**

```bash
npm install     # first time only
npm run dev
```

Open **http://localhost:5173**.

The dev server proxies `/incidents`, `/health`, and `/suppressions` to
`localhost:8000`, so no CORS configuration is needed on the backend.

## If the incident list looks stale

The backend seeds its SQLite store (`data/incidents.db`) with `INSERT OR IGNORE` —
it adds new demo incidents but never deletes old rows. After pulling new demo
data, reset it:

```bash
rm -f data/incidents.db   # from repo root; reseeds on next backend start
```

## Views

- **Unified incidents** — the fused cross-domain incident list; click any card
  for the evidence detail view (split PS1 / PS2 panels, analyst feedback actions).
- **PS1 · Behavioral / PS2 · Transactions** — each detector's raw signals alone,
  before correlation.
