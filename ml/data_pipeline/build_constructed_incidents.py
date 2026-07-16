"""Build clearly-labeled CONSTRUCTED single-domain demo incidents.

These are NOT real detections. They exist only so the dashboard shows the full
access-decision spectrum (step-up / throttle) next to the real corroborated
REVOKE incidents (E027/E028/E029). Same honesty discipline as demo_scenarios.json:
everything constructed is labeled; anything real is cited.

Scenario A (PS2-only, E010): a large *legitimate-looking* CASH_OUT (isFraud=0) with
NO behavioral corroboration -> STEP-UP (a realistic false positive we verify rather
than auto-revoke). NOTE: the production fraud model is effectively binary on PaySim
(a full feature sweep finds no score between ~0.55 and ~0.9), so a genuine mid-range
*model* score does not exist. The 0.78 here is therefore a SET-FOR-DEMO value,
explicitly labeled -- not a live model output.

Scenario B (PS1-only, E015): a REAL off-hours CERT logon for the mapped username,
with NO transactional corroboration -> THROTTLE. The logon row is real and cited;
the behavioral risk (0.60) is a documented heuristic.

Output: data/synthetic/constructed_incidents.json
Run: python3 ml/data_pipeline/build_constructed_incidents.py [--root .]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

MAPPING_PATH = "data/synthetic/entity_mapping.json"
CERT_LOGON = "data/raw/cert_insider_threat/logon.csv"
OUTPUT_PATH = "data/synthetic/constructed_incidents.json"

SCENARIO_A_ENTITY = "E010"   # payments_analyst — PS2-only false positive
SCENARIO_B_ENTITY = "E015"   # operations_analyst — PS1-only off-hours access
A_SCORE = 0.78
B_SCORE = 0.60


def _mapping(root: Path) -> dict[str, dict]:
    data = json.loads((root / MAPPING_PATH).read_text(encoding="utf-8"))
    return {e["entity"]["entity_id"]: e for e in data["entities"]}


def _first_off_hours_logon(root: Path, user: str) -> dict:
    df = pd.read_csv(root / CERT_LOGON)
    df.columns = [c.lower() for c in df.columns]
    df = df[(df["user"] == user) & (df["activity"] == "Logon")].copy()
    df["dt"] = pd.to_datetime(df["date"], format="%m/%d/%Y %H:%M:%S", errors="raise")
    df["hour"] = df["dt"].dt.hour
    off = df[(df["hour"] < 7) | (df["hour"] >= 19)].sort_values("dt")
    if off.empty:
        raise SystemExit(f"No off-hours logon found for {user}")
    r = off.iloc[0]
    return {"id": str(r["id"]), "timestamp": r["dt"].strftime("%Y-%m-%d %H:%M:%S"), "pc": str(r["pc"])}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=".")
    args = ap.parse_args()
    root = Path(args.root).resolve()
    mapping = _mapping(root)

    a = mapping[SCENARIO_A_ENTITY]
    a_acct = a["source_ids"]["paysim"]["nameOrig"]
    a_role = a["entity"].get("role")

    b = mapping[SCENARIO_B_ENTITY]
    b_user = b["source_ids"]["cert"]["user"]
    b_role = b["entity"].get("role")
    logon = _first_off_hours_logon(root, b_user)

    payload = {
        "note": (
            "CONSTRUCTED single-domain demo incidents (NOT real detections), added so the "
            "dashboard shows the full decision spectrum (step-up / throttle) alongside the real "
            "corroborated REVOKE incidents. Same honesty discipline as demo_scenarios.json."
        ),
        "assessments": [
            {
                "entity_id": SCENARIO_A_ENTITY,
                "score": A_SCORE,
                "constructed": True,
                "reasons": [
                    {
                        "signal_name": "suspected_fraud_uncorroborated",
                        "domain": "ps2_transaction",
                        "weight": A_SCORE,
                        "raw_value": (
                            f"CONSTRUCTED demo (not a real detection): a large legitimate-looking "
                            f"CASH_OUT (isFraud=0) on {a_role} {SCENARIO_A_ENTITY}'s account {a_acct}. "
                            f"Fraud-risk {A_SCORE} is a SET-FOR-DEMO value -- the PaySim model is "
                            f"near-binary (no genuine mid-range score exists), so a moderate score is "
                            f"itself synthetic. No behavioral (PS1) corroboration -> confidence low -> "
                            f"STEP-UP verification, not revoke (realistic false-positive handling)."
                        ),
                    }
                ],
            },
            {
                "entity_id": SCENARIO_B_ENTITY,
                "score": B_SCORE,
                "constructed": True,
                "reasons": [
                    {
                        "signal_name": "off_hours_logon",
                        "domain": "ps1_behavioral",
                        "weight": B_SCORE,
                        "raw_value": (
                            f"CONSTRUCTED demo scenario built on a REAL CERT event: off-hours logon "
                            f"(row {logon['id']}) at {logon['timestamp']} on {logon['pc']} by {b_user} "
                            f"({b_role} {SCENARIO_B_ENTITY}). Behavioral risk {B_SCORE} is a documented "
                            f"heuristic. No transactional (PS2) corroboration -> confidence low -> THROTTLE."
                        ),
                    }
                ],
            },
        ],
    }
    (root / OUTPUT_PATH).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {OUTPUT_PATH}")
    print(f"  A {SCENARIO_A_ENTITY} PS2-only score {A_SCORE} (constructed) -> expect step_up_auth")
    print(f"  B {SCENARIO_B_ENTITY} PS1-only score {B_SCORE} (real logon {logon['id']}) -> expect throttle")


if __name__ == "__main__":
    main()
