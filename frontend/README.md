# VaultWatch Frontend

React + Tailwind + Vite dashboard for the VaultWatch correlation API.

## The idea behind the design

The product's whole claim is that **two weak signals converging in time** beat one
loud alert. Most security dashboards bury that in a table of badges. Here it's the
main visual instead:

- **PS1 (behavioural)** rides the lane above a time axis, **PS2 (transaction)**
  below. The two are opposite colour temperatures — warm amber vs cool cyan — so
  their meeting reads as two genuinely different things converging.
- A signal only **drops onto the decision axis** when the other domain also fired
  for that same entity inside the 120-minute correlation window. The connecting
  stem runs amber → red → cyan: two sources igniting into one decision.
- A **lone signal** stays on its lane, stays hollow, and never reaches the axis —
  the false-positive defence, made literal.
- Signals with **no event time** are shown off-axis entirely, because per the
  engine they can never enter a correlation window.

## Run locally

Prereqs: Node 18+, plus the backend running (`pip install -r backend/requirements.txt`).

**Terminal 1 — backend (from repo root):**

```bash
python3 -m uvicorn backend.app.main:app --port 8000
```

**Terminal 2 — frontend (from this directory):**

```bash
npm install     # first time only
npm run dev
```

Open **http://localhost:5173**. The dev server proxies all API routes to
`localhost:8000`, so no CORS configuration is needed. Point it elsewhere with
`VITE_API_TARGET=http://host:port npm run dev`.

Fonts are self-hosted (`@fontsource`) so typography survives a demo room with no
wifi.

## Views

- **Convergence** — the timeline, plus the incident ledger. Click any node or row
  to open the case: the 120-minute window drawn to scale with the measured gap
  between the two domains, per-signal evidence with weights, and the decision gate
  showing exactly why revoke was or wasn't unlocked.
- **PS1 · Behavioural** / **PS2 · Transaction** — what each detector sees on its
  own, before correlation, with its score distribution.
- **Quantum** — crypto inventory ranked for PQC migration priority, HNDL exposure
  flagged.

## Live injection

**Inject signal** (top right) posts *unscored* payloads to `/ingest/behavioral`
and `/ingest/transaction`; the server runs the models in-process and re-correlates.
Two steps on purpose: the first signal lands alone and is capped at step-up, the
second corroborates it and unlocks revoke.

Needs the backend's `VAULTWATCH_INGESTION_API_KEY`, entered in the panel (or set
`VITE_INGESTION_KEY`). This is a **demo control** — the key travels from the
browser. In a real deployment a detector publishes server-side over HTTP or Kafka
and the browser never holds it.

## URL parameters

Deep-linkable, so a specific case can be pasted to a colleague:

- `?incident=<id>` — open a case
- `?view=ps1|ps2|quantum` — open a view
- `?inject=1` — open the injection panel

## If the incident list looks stale

The backend seeds SQLite (`data/incidents.db`) with `INSERT OR IGNORE` — it adds
rows but never removes them, so restarts can accumulate duplicates:

```bash
rm -f data/incidents.db   # from repo root; reseeds on next backend start
```
