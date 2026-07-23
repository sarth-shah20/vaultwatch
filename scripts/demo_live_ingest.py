"""Live "inject a signal, watch it escalate" demo driver.

POSTs two committed demo inputs to the live-scoring endpoints:
  1. a real prepared CERT behavioral window  -> POST /ingest/behavioral
  2. a realistic transaction feature row      -> POST /ingest/transaction
Both name the same demo entity (E027), so the second signal corroborates the
first inside the temporal window and the incident escalates to a high-confidence
REVOKE. The server runs the models in-process; nothing is pre-scored.

Prereqs: a running API with VAULTWATCH_INGESTION_API_KEY set, and the CERT
behavioral joblib artifact present (gitignored; retrain or copy in). The fraud
model is committed, so the transaction leg works on a fresh clone.

Usage:
  VAULTWATCH_INGESTION_API_KEY=... python scripts/demo_live_ingest.py
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
BASE = os.getenv("VAULTWATCH_API_BASE", "http://127.0.0.1:8000")


def _load(rel_path: str) -> dict:
    payload = json.loads((ROOT / rel_path).read_text(encoding="utf-8"))
    payload.pop("_label", None)  # request models forbid extra fields
    return payload


def main() -> int:
    key = os.getenv("VAULTWATCH_INGESTION_API_KEY")
    if not key:
        print("set VAULTWATCH_INGESTION_API_KEY to the API's configured ingestion key", file=sys.stderr)
        return 2
    headers = {"X-Ingestion-API-Key": key}

    behavioral = httpx.post(f"{BASE}/ingest/behavioral", headers=headers, json=_load("data/synthetic/live_demo_behavioral_window.json"), timeout=60).json()
    print("PS1 behavioral:", json.dumps({k: behavioral.get(k) for k in ("alerted", "score", "entity_id", "domain")}))

    transaction = httpx.post(f"{BASE}/ingest/transaction", headers=headers, json=_load("data/synthetic/live_demo_transaction.json"), timeout=60).json()
    print("PS2 transaction:", json.dumps({k: transaction.get(k) for k in ("scored", "score", "entity_id", "domain")}))

    incident_ids = transaction.get("affected_incident_ids") or behavioral.get("affected_incident_ids") or []
    if not incident_ids:
        print("no incident produced — check the ingestion key and that both legs scored", file=sys.stderr)
        return 1
    incident = httpx.get(f"{BASE}/incidents/{incident_ids[0]}", timeout=30).json()
    print("\nCorrelated incident (live):")
    print(json.dumps({
        "incident_id": incident.get("incident_id"),
        "entity_id": incident.get("entity_id"),
        "combined_score": incident.get("combined_score"),
        "confidence": incident.get("confidence"),
        "access_decision": incident.get("access_decision"),
        "contributing_domains": incident.get("contributing_domains"),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
