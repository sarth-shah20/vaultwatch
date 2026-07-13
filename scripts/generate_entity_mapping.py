"""Generate a committed demo entity mapping from the raw CERT and PaySim CSVs."""

from __future__ import annotations

import csv
import json
import random
from pathlib import Path


DEMO_ENTITY_COUNT = 30
RANDOM_SEED = 42

REPO_ROOT = Path(__file__).resolve().parents[1]
CERT_LOGON_PATH = REPO_ROOT / "data/raw/cert_insider_threat/logon.csv"
PAYSIM_PATH = REPO_ROOT / "data/raw/paysim/PS_20174392719_1491204439457_log.csv"
OUTPUT_PATH = REPO_ROOT / "data/synthetic/entity_mapping.json"


def _read_distinct_cert_users() -> list[str]:
    users: set[str] = set()

    with CERT_LOGON_PATH.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            users.add(row["user"])

    return sorted(users)


def _read_distinct_paysim_accounts() -> list[str]:
    accounts: set[str] = set()

    with PAYSIM_PATH.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            account_id = row["nameOrig"]
            if account_id.startswith("C"):
                accounts.add(account_id)

    return sorted(accounts)


def _build_mapping() -> dict:
    cert_users = _read_distinct_cert_users()
    paysim_accounts = _read_distinct_paysim_accounts()

    if len(cert_users) < DEMO_ENTITY_COUNT:
        raise ValueError(
            f"Expected at least {DEMO_ENTITY_COUNT} CERT users, found {len(cert_users)}."
        )

    if len(paysim_accounts) < DEMO_ENTITY_COUNT:
        raise ValueError(
            "Expected at least "
            f"{DEMO_ENTITY_COUNT} PaySim origin accounts, found {len(paysim_accounts)}."
        )

    rng = random.Random(RANDOM_SEED)
    sampled_cert_users = rng.sample(cert_users, DEMO_ENTITY_COUNT)
    sampled_paysim_accounts = rng.sample(paysim_accounts, DEMO_ENTITY_COUNT)

    entities = []
    for index, (cert_user, paysim_account) in enumerate(
        zip(sampled_cert_users, sampled_paysim_accounts),
        start=1,
    ):
        entity_id = f"E{index:03d}"
        entities.append(
            {
                "entity": {
                    "entity_id": entity_id,
                    "entity_type": "human",
                    "display_name": cert_user,
                    "role": None,
                    "privilege_level": "standard",
                    "department": None,
                    "active": True,
                    "employment_end_date": None,
                    "hr_flag": None,
                },
                "source_ids": {
                    "cert": {"user": cert_user},
                    "paysim": {"nameOrig": paysim_account},
                    "telemetry": {
                        "device_ids": [f"DEV-{1000 + index}"],
                        "ip_addresses": [f"10.42.0.{index}"],
                    },
                },
            }
        )

    return {"entities": entities}


def main() -> None:
    mapping = _build_mapping()
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(mapping, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(mapping['entities'])} entities to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
