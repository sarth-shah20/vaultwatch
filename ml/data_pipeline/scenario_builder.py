"""Step 3 — grounded PS1 + PS2 demo scenario builder (the "bridge" layer).

This does NOT generate a telemetry stream. It CURATES 3 concrete, timed attack
scenarios from the REAL data we already have, so the correlation engine (Step 6)
has same-entity, same-window PS1 (CERT behavioral) + PS2 (PaySim transactional)
signals to join.

For each of 3 demo entities that have a REAL fraudulent PaySim transaction
(isFraud=1) on their mapped account, we:
  1. Read their REAL CERT logon/device rows (by mapped CERT username) and pick a
     real anomaly relative to their own baseline (priority: off-hours logon ->
     off-hours device connect -> weekend logon -> weekend device connect). If no
     natural anomaly exists in the data, ONE synthetic row is injected and
     clearly labelled `source="injected"` (not passed off as real).
  2. Pair it with their REAL isFraud=1 PaySim transaction (or, if none, ONE
     clearly-labelled injected transaction).
  3. Define an incident window. NOTE: CERT (absolute 2010-2011 timestamps) and
     PaySim (relative hourly `step`, no absolute date) are independent
     simulations with no shared clock, so the minutes-apart alignment between the
     two is a CURATED demo bridge (`curated_alignment=true`). The CERT timestamp
     is real and the PaySim step is real; only their relative placement is
     constructed.

Output: data/synthetic/demo_scenarios.json.
Run: python3 ml/data_pipeline/scenario_builder.py [--root .]
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

CERT_DATE_FMT = "%m/%d/%Y %H:%M:%S"

# Anchors: entities with a REAL isFraud=1 PaySim transaction. Curated gap places
# that real transaction inside the CERT incident window for the demo.
ANCHORS = [
    {"entity_id": "E028", "curated_gap_minutes": 37},
    {"entity_id": "E027", "curated_gap_minutes": 52},
    {"entity_id": "E029", "curated_gap_minutes": 44},
]

CERT_DIR = "data/raw/cert_insider_threat"
PAYSIM_DIR = "data/raw/paysim"
MAPPING_PATH = "data/synthetic/entity_mapping.json"
OUTPUT_PATH = "data/synthetic/demo_scenarios.json"


def _off_hours(hour: int) -> bool:
    return hour < 7 or hour >= 19


def load_mapping(root: Path) -> dict[str, dict]:
    payload = json.loads((root / MAPPING_PATH).read_text(encoding="utf-8"))
    out = {}
    for record in payload["entities"]:
        ent = record["entity"]
        out[ent["entity_id"]] = {
            "cert_user": record["source_ids"]["cert"]["user"],
            "paysim_nameOrig": record["source_ids"]["paysim"]["nameOrig"],
            "role": ent.get("role"),
            "entity_type": ent.get("entity_type"),
        }
    return out


def load_cert(root: Path, users: set[str]) -> tuple[pd.DataFrame, pd.DataFrame]:
    def _read(name: str) -> pd.DataFrame:
        df = pd.read_csv(root / CERT_DIR / name)
        df.columns = [c.lower() for c in df.columns]
        df = df[df["user"].isin(users)].copy()
        df["dt"] = pd.to_datetime(df["date"], format=CERT_DATE_FMT, errors="coerce")
        df["hour"] = df["dt"].dt.hour
        df["weekday"] = df["dt"].dt.dayofweek
        df["activity"] = df["activity"].astype("string")
        return df.sort_values("dt", kind="mergesort")

    return _read("logon.csv"), _read("device.csv")


def load_paysim_fraud(root: Path, accounts: set[str]) -> pd.DataFrame:
    usecols = ["step", "type", "amount", "nameOrig", "isFraud"]
    csv = next((root / PAYSIM_DIR).glob("*.csv"))
    df = pd.read_csv(csv, usecols=usecols)
    df = df[df["nameOrig"].isin(accounts)].copy()
    return df[df["isFraud"] == 1]


def _baseline_note(user_logons: pd.DataFrame) -> str:
    weekday = user_logons[user_logons["weekday"] < 5]
    hours = weekday["hour"].dropna()
    if hours.empty:
        return "no weekday logon baseline available"
    return (
        f"user's typical weekday logons run {int(hours.min())}:00-{int(hours.max())}:00 "
        f"(median start {int(hours.median())}:00) across {len(user_logons)} logons"
    )


def pick_cert_anomaly(user: str, logon: pd.DataFrame, device: pd.DataFrame) -> dict:
    """Pick the strongest REAL anomaly for this user, or inject one if none exists."""
    u_logon = logon[logon["user"] == user]
    u_device = device[device["user"] == user]
    logons = u_logon[u_logon["activity"] == "Logon"]
    connects = u_device[u_device["activity"] == "Connect"]
    baseline = _baseline_note(u_logon)

    def real(kind: str, row: pd.Series, why: str) -> dict:
        return {
            "source": "real_cert",
            "injected": False,
            "kind": kind,
            "cert_row_id": str(row["id"]),
            "timestamp": row["dt"].strftime("%Y-%m-%d %H:%M:%S"),
            "pc": str(row["pc"]),
            "activity": str(row["activity"]),
            "baseline_note": baseline,
            "why_anomalous": why,
        }

    off_logon = logons[logons["hour"].apply(_off_hours)]
    if not off_logon.empty:
        r = off_logon.iloc[0]
        return real("off_hours_logon", r, f"logon at {r['dt'].strftime('%H:%M')} is outside the 07:00-19:00 workday")

    off_conn = connects[connects["hour"].apply(_off_hours)]
    if not off_conn.empty:
        r = off_conn.iloc[0]
        return real("off_hours_device_connect", r, f"USB/device connect at {r['dt'].strftime('%H:%M')} is off-hours")

    wknd_logon = logons[logons["weekday"] >= 5]
    if not wknd_logon.empty:
        r = wknd_logon.iloc[0]
        return real("weekend_logon", r, f"logon on {r['dt'].strftime('%A')} is outside the user's weekday pattern")

    wknd_conn = connects[connects["weekday"] >= 5]
    if not wknd_conn.empty:
        r = wknd_conn.iloc[0]
        return real("weekend_device_connect", r, f"USB/device connect on {r['dt'].strftime('%A')} is outside the weekday pattern")

    # Fallback: no natural anomaly in the real data -> inject ONE, clearly labelled.
    anchor = (logons["dt"].max() if not logons.empty else pd.Timestamp("2010-01-04 09:00:00"))
    injected_ts = (anchor.normalize() + timedelta(hours=2, minutes=17))  # 02:17 off-hours
    return {
        "source": "injected",
        "injected": True,
        "kind": "off_hours_logon",
        "cert_row_id": None,
        "timestamp": injected_ts.strftime("%Y-%m-%d %H:%M:%S"),
        "pc": "INJECTED",
        "activity": "Logon",
        "baseline_note": baseline,
        "why_anomalous": "no natural CERT anomaly for this user in the data; injected one off-hours logon for the demo",
    }


def pick_paysim_txn(nameOrig: str, fraud_df: pd.DataFrame) -> dict:
    rows = fraud_df[fraud_df["nameOrig"] == nameOrig]
    if not rows.empty:
        r = rows.sort_values("amount", ascending=False).iloc[0]
        return {
            "source": "real_paysim",
            "injected": False,
            "nameOrig": nameOrig,
            "step": int(r["step"]),
            "type": str(r["type"]),
            "amount": float(r["amount"]),
            "isFraud": 1,
        }
    return {
        "source": "injected",
        "injected": True,
        "nameOrig": nameOrig,
        "step": None,
        "type": "TRANSFER",
        "amount": 500000.0,
        "isFraud": 1,
        "note": "no real isFraud=1 transaction for this account; injected a high-risk transfer for the demo",
    }


def build_scenario(idx: int, anchor: dict, mapping: dict, logon, device, fraud_df) -> dict:
    entity_id = anchor["entity_id"]
    info = mapping[entity_id]
    user, account = info["cert_user"], info["paysim_nameOrig"]

    cert_event = pick_cert_anomaly(user, logon, device)
    paysim_txn = pick_paysim_txn(account, fraud_df)

    anchor_dt = datetime.strptime(cert_event["timestamp"], "%Y-%m-%d %H:%M:%S")
    gap = anchor["curated_gap_minutes"]
    paysim_time = anchor_dt + timedelta(minutes=gap)

    amount = paysim_txn["amount"]
    narrative = (
        f"{entity_id} ({info['role']}): {cert_event['kind'].replace('_', ' ')} "
        f"({'real' if not cert_event['injected'] else 'injected'} CERT event at "
        f"{cert_event['timestamp']}), then ~{gap} min later a {paysim_txn['type']} of "
        f"{amount:,.0f} on their account ({'real isFraud=1' if not paysim_txn['injected'] else 'injected'} "
        f"PaySim transaction) — a single privileged actor whose behavioral and transactional "
        f"signals both spike inside one window."
    )

    return {
        "scenario_id": f"S{idx}",
        "entity_id": entity_id,
        "cert_user": user,
        "paysim_account": account,
        "role": info["role"],
        "narrative": narrative,
        "incident_window": {
            "anchor_time": cert_event["timestamp"],
            "curated_gap_minutes": gap,
            "paysim_curated_time": paysim_time.strftime("%Y-%m-%d %H:%M:%S"),
            "curated_alignment": True,
            "alignment_note": (
                "CERT timestamp and PaySim step are both REAL; the minutes-apart placement is a "
                "curated demo bridge because CERT (absolute dates) and PaySim (relative hourly step) "
                "are independent simulations with no shared clock."
            ),
        },
        "cert_event": cert_event,
        "paysim_transaction": paysim_txn,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".")
    args = parser.parse_args()
    root = Path(args.root).resolve()

    mapping = load_mapping(root)
    users = {mapping[a["entity_id"]]["cert_user"] for a in ANCHORS}
    accounts = {mapping[a["entity_id"]]["paysim_nameOrig"] for a in ANCHORS}

    print(f"Loading CERT for {len(users)} users and PaySim fraud for {len(accounts)} accounts ...")
    logon, device = load_cert(root, users)
    fraud_df = load_paysim_fraud(root, accounts)

    scenarios = [
        build_scenario(i, anchor, mapping, logon, device, fraud_df)
        for i, anchor in enumerate(ANCHORS, start=1)
    ]

    summary = {
        "scenarios": len(scenarios),
        "real_cert_events": sum(1 for s in scenarios if not s["cert_event"]["injected"]),
        "injected_cert_events": sum(1 for s in scenarios if s["cert_event"]["injected"]),
        "real_paysim_txns": sum(1 for s in scenarios if not s["paysim_transaction"]["injected"]),
        "injected_paysim_txns": sum(1 for s in scenarios if s["paysim_transaction"]["injected"]),
    }
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "purpose": "Grounded PS1(CERT)+PS2(PaySim) demo scenarios for the Step 6 correlation engine.",
        "methodology": (
            "Each scenario pairs one entity's REAL CERT behavioral anomaly with their REAL isFraud=1 "
            "PaySim transaction. Cross-dataset time alignment is curated (see incident_window). Any "
            "synthetic row is labelled source='injected'; nothing injected is presented as real."
        ),
        "summary": summary,
        "scenarios": scenarios,
    }

    out = root / OUTPUT_PATH
    out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(scenarios)} scenarios -> {OUTPUT_PATH}")
    print(f"Summary: {summary}")
    for s in scenarios:
        print(f"  {s['scenario_id']} {s['entity_id']} | CERT {s['cert_event']['kind']} "
              f"({s['cert_event']['source']}) | PaySim {s['paysim_transaction']['type']} "
              f"{s['paysim_transaction']['amount']:,.0f} ({s['paysim_transaction']['source']})")


if __name__ == "__main__":
    main()
