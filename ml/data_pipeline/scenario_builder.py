"""Step 3 (integrated) — grounded PS1 + PS2 demo scenarios (the "bridge" layer).

Pairs each demo entity's REAL PS1 behavioral anomaly with their REAL isFraud=1
PaySim transaction, so the Step 6 correlation engine has same-entity signals from
both domains to join.

PS1 side: the teammate's Isolation Forest flags an anomaly on a DTAA user; we
resolve that user to our entity_id via the `ps1` crosswalk in entity_mapping.json
and take their strongest flagged anomaly from ps1_anomaly_results.json.
PS2 side: the entity's real fraudulent PaySim transaction.

Honesty: both the PS1 anomaly and the PaySim transaction are REAL model/data
outputs. Two things are deliberate, labeled demo constructs: (1) the entity <->
DTAA-user crosswalk (no dataset naturally links CERT identities to PaySim
accounts), and (2) the cross-dataset time alignment (`curated_alignment: true`)
— PS1 dates are absolute, PaySim uses a relative step, so we place the real
PaySim fraud a plausible gap after the real PS1 anomaly.

Output: data/synthetic/demo_scenarios.json
Run: python3 ml/data_pipeline/scenario_builder.py [--root .]
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from backend.app.ps2_correlation.ps1_adapter import normalize_score

ANCHORS = [
    {"entity_id": "E028", "curated_gap_minutes": 37},
    {"entity_id": "E027", "curated_gap_minutes": 52},
    {"entity_id": "E029", "curated_gap_minutes": 44},
]

MAPPING_PATH = "data/synthetic/entity_mapping.json"
PS1_ANOMALIES_PATH = "data/synthetic/ps1_anomaly_results.json"
PAYSIM_DIR = "data/raw/paysim"
OUTPUT_PATH = "data/synthetic/demo_scenarios.json"


def load_mapping(root: Path) -> dict[str, dict]:
    payload = json.loads((root / MAPPING_PATH).read_text(encoding="utf-8"))
    out = {}
    for record in payload["entities"]:
        ps1 = record["source_ids"].get("ps1") or {}
        out[record["entity"]["entity_id"]] = {
            "role": record["entity"].get("role"),
            "paysim_account": record["source_ids"]["paysim"]["nameOrig"],
            "ps1_user": ps1.get("user"),
        }
    return out


def strongest_ps1_anomaly_by_user(root: Path) -> dict[str, dict]:
    """Return {ps1_user: strongest (most anomalous) anomaly} from the PS1 output."""
    payload = json.loads((root / PS1_ANOMALIES_PATH).read_text(encoding="utf-8"))
    best: dict[str, dict] = {}
    for anomaly in payload.get("anomalies", []):
        log = json.loads(anomaly["log"])
        user = log.get("USER")
        if user is None:
            continue
        rec = {
            "activity": log["ACTIVITY"],
            "pc": log["PC"],
            "timestamp": f"{log['DATE']} {log['HOUR']}:{log['MINUTE']}:{log.get('SECOND', '00')}",
            "decision_function_score": float(anomaly["score"]),
            "detector_reason": anomaly["reason"],
        }
        if user not in best or rec["decision_function_score"] < best[user]["decision_function_score"]:
            best[user] = rec
    return best


def paysim_fraud_by_account(root: Path, accounts: set[str]) -> dict[str, dict]:
    import pandas as pd

    csv = next((root / PAYSIM_DIR).glob("*.csv"))
    df = pd.read_csv(csv, usecols=["step", "type", "amount", "nameOrig", "isFraud"])
    df = df[(df["nameOrig"].isin(accounts)) & (df["isFraud"] == 1)]
    out = {}
    for name, grp in df.groupby("nameOrig"):
        row = grp.sort_values("amount", ascending=False).iloc[0]
        out[name] = {"step": int(row["step"]), "type": str(row["type"]), "amount": float(row["amount"])}
    return out


def build_scenario(idx: int, anchor: dict, mapping: dict, ps1_by_user: dict, fraud_by_acct: dict) -> dict:
    eid = anchor["entity_id"]
    info = mapping[eid]
    user, account = info["ps1_user"], info["paysim_account"]

    a = ps1_by_user[user]
    ps1_event = {
        "source": "real_ps1_isolation_forest",
        "injected": False,
        "ps1_user": user,
        "activity": a["activity"],
        "pc": a["pc"],
        "timestamp": a["timestamp"],
        "decision_function_score": a["decision_function_score"],
        "normalized_risk": normalize_score(a["decision_function_score"]),
        "detector_reason": a["detector_reason"],
    }
    f = fraud_by_acct[account]
    paysim_txn = {"source": "real_paysim", "injected": False, "nameOrig": account,
                  "step": f["step"], "type": f["type"], "amount": f["amount"], "isFraud": 1}

    anchor_dt = datetime.strptime(ps1_event["timestamp"], "%Y-%m-%d %H:%M:%S")
    gap = anchor["curated_gap_minutes"]
    paysim_time = anchor_dt + timedelta(minutes=gap)

    narrative = (
        f"{eid} ({info['role']}): PS1 flags '{a['activity']}' (real Isolation-Forest anomaly, "
        f"risk {ps1_event['normalized_risk']:.2f}) at {a['timestamp']}, then ~{gap} min later a "
        f"{f['type']} of {f['amount']:,.0f} on their account (real PaySim isFraud=1) — one actor, "
        f"a behavioral red flag and a fraudulent transaction inside a single window."
    )

    return {
        "scenario_id": f"S{idx}",
        "entity_id": eid,
        "role": info["role"],
        "ps1_user": user,
        "paysim_account": account,
        "narrative": narrative,
        "incident_window": {
            "anchor_time": ps1_event["timestamp"],
            "curated_gap_minutes": gap,
            "paysim_curated_time": paysim_time.strftime("%Y-%m-%d %H:%M:%S"),
            "curated_alignment": True,
            "alignment_note": (
                "PS1 anomaly and PaySim transaction are both REAL; the minutes-apart placement and the "
                "entity<->DTAA-user crosswalk are deliberate labeled demo constructs (independent datasets, "
                "no shared clock or identity)."
            ),
        },
        "ps1_event": ps1_event,
        "paysim_transaction": paysim_txn,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".")
    args = parser.parse_args()
    root = Path(args.root).resolve()

    mapping = load_mapping(root)
    ps1_by_user = strongest_ps1_anomaly_by_user(root)
    accounts = {mapping[a["entity_id"]]["paysim_account"] for a in ANCHORS}
    fraud_by_acct = paysim_fraud_by_account(root, accounts)

    scenarios = [build_scenario(i, a, mapping, ps1_by_user, fraud_by_acct)
                 for i, a in enumerate(ANCHORS, start=1)]

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "purpose": "Grounded PS1(behavioral)+PS2(transactional) demo scenarios for the Step 6 correlation engine.",
        "methodology": (
            "Each scenario pairs an entity's REAL PS1 Isolation-Forest anomaly (teammate's DTAA dataset, "
            "resolved via the ps1 crosswalk) with their REAL isFraud=1 PaySim transaction. The entity<->"
            "DTAA-user crosswalk and the cross-dataset time alignment are deliberate, labeled demo constructs; "
            "the anomaly and the transaction are real."
        ),
        "summary": {
            "scenarios": len(scenarios),
            "real_ps1_anomalies": sum(1 for s in scenarios if not s["ps1_event"]["injected"]),
            "real_paysim_txns": sum(1 for s in scenarios if not s["paysim_transaction"]["injected"]),
            "injected": 0,
        },
        "scenarios": scenarios,
    }
    (root / OUTPUT_PATH).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(scenarios)} scenarios -> {OUTPUT_PATH}")
    for s in scenarios:
        p, f = s["ps1_event"], s["paysim_transaction"]
        print(f"  {s['scenario_id']} {s['entity_id']} | PS1 {p['ps1_user']}:{p['activity']} "
              f"(risk {p['normalized_risk']:.2f}) | PS2 {f['type']} {f['amount']:,.0f}")


if __name__ == "__main__":
    main()
