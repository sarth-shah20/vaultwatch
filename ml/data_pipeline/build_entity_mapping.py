"""Build synthetic entity mappings backed by active CERT and PaySim identifiers."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from ml.data_pipeline.paysim_features import DEFAULT_ENTITY_MAPPING_PATH, load_paysim

DEFAULT_CERT_LOGON_PATH = Path("data/raw/cert_insider_threat/logon.csv")
DEFAULT_PAYSIM_RAW_DIR = Path("data/raw/paysim")
DEFAULT_OUTPUT_PATH = Path("data/processed/entity_mapping.json")
DEFAULT_MIRROR_OUTPUT_PATH = DEFAULT_ENTITY_MAPPING_PATH

ENTITY_COUNT = 30
NORMAL_COUNT = 20
PRIVILEGED_COUNT = 6
FRAUD_SCENARIO_COUNT = 4
SERVICE_ACCOUNT_COUNT = 5

PRIVILEGED_ROLES = ("database_admin", "finance_ops", "system_admin")
NORMAL_ROLES = ("employee", "payments_analyst", "operations_analyst", "support_analyst")
FRAUD_SCENARIO_ROLES = ("finance_analyst", "payments_operator", "operations_analyst")
DEPARTMENTS = ("IT", "Finance", "Operations")


def get_active_paysim_accounts(paysim_df: pd.DataFrame, min_txn: int = 1) -> pd.DataFrame:
    """Summarize active PaySim origin accounts and filter to minimum activity."""

    if min_txn < 1:
        raise ValueError("min_txn must be at least 1")

    required_columns = {
        "step",
        "type",
        "amount",
        "nameOrig",
        "nameDest",
        "isFraud",
        "isFlaggedFraud",
    }
    missing_columns = required_columns.difference(paysim_df.columns)
    if missing_columns:
        missing = ", ".join(sorted(missing_columns))
        raise ValueError(f"Missing required PaySim columns: {missing}")

    df = paysim_df.copy()
    df["type"] = df["type"].astype("string")
    df["nameOrig"] = df["nameOrig"].astype("string")
    df["step"] = pd.to_numeric(df["step"], errors="raise")
    df["amount"] = pd.to_numeric(df["amount"], errors="raise")
    df["isFraud"] = pd.to_numeric(df["isFraud"], errors="raise")
    df["isFlaggedFraud"] = pd.to_numeric(df["isFlaggedFraud"], errors="raise")

    grouped = df.groupby("nameOrig", observed=False)
    accounts = grouped.agg(
        total_txn_count=("nameOrig", "size"),
        total_amount=("amount", "sum"),
        fraud_count=("isFraud", "sum"),
        flagged_fraud_count=("isFlaggedFraud", "sum"),
    )

    transfer_counts = df[df["type"] == "TRANSFER"].groupby("nameOrig", observed=False).size()
    cashout_counts = df[df["type"] == "CASH_OUT"].groupby("nameOrig", observed=False).size()
    accounts["transfer_count"] = transfer_counts
    accounts["cashout_count"] = cashout_counts
    accounts[["transfer_count", "cashout_count"]] = accounts[
        ["transfer_count", "cashout_count"]
    ].fillna(0)

    pattern_accounts = _find_transfer_then_cashout_accounts(df)
    accounts["has_transfer_then_cashout"] = accounts.index.isin(pattern_accounts)

    accounts = accounts.reset_index()
    integer_columns = (
        "total_txn_count",
        "transfer_count",
        "cashout_count",
        "fraud_count",
        "flagged_fraud_count",
    )
    for column in integer_columns:
        accounts[column] = accounts[column].astype("int64")

    accounts = accounts[accounts["total_txn_count"] >= min_txn]
    return accounts.sort_values(
        ["total_txn_count", "total_amount", "nameOrig"],
        ascending=[False, False, True],
        kind="mergesort",
    ).reset_index(drop=True)


def load_cert_users(path: str, limit: int = 30) -> list[str]:
    """Load distinct CERT user IDs from logon.csv in file order."""

    if limit < 1:
        raise ValueError("limit must be at least 1")

    cert_df = pd.read_csv(path, usecols=["user"])
    users = cert_df["user"].dropna().astype(str).drop_duplicates().tolist()
    if len(users) < limit:
        raise ValueError(f"Need {limit} distinct CERT users, found {len(users)}")
    return users[:limit]


def select_paysim_accounts(active_accounts: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Select normal, privileged-looking, and fraud-scenario account buckets."""

    required_columns = {
        "nameOrig",
        "total_txn_count",
        "total_amount",
        "fraud_count",
        "flagged_fraud_count",
        "transfer_count",
        "cashout_count",
        "has_transfer_then_cashout",
    }
    missing_columns = required_columns.difference(active_accounts.columns)
    if missing_columns:
        missing = ", ".join(sorted(missing_columns))
        raise ValueError(f"Missing required account summary columns: {missing}")

    pool = active_accounts.copy().reset_index(drop=True)
    fraud_pool = pool[
        (pool["has_transfer_then_cashout"])
        | (pool["fraud_count"] > 0)
    ].copy()
    print(f"Total active PaySim accounts available: {len(pool):,}")
    print(f"Fraud scenario pool size: {len(fraud_pool):,}")
    if len(fraud_pool) < FRAUD_SCENARIO_COUNT:
        raise ValueError(
            "Not enough fraud_scenario PaySim accounts: "
            f"need {FRAUD_SCENARIO_COUNT}, found {len(fraud_pool)}"
        )

    fraud = _take_ranked(
        fraud_pool,
        FRAUD_SCENARIO_COUNT,
        category="fraud_scenario",
        sort_columns=("fraud_count", "has_transfer_then_cashout", "total_txn_count", "total_amount", "nameOrig"),
        ascending=(False, False, False, False, True),
    )

    selected_fraud_names = set(fraud["nameOrig"])
    privileged_pool = pool[~pool["nameOrig"].isin(selected_fraud_names)].copy()
    print(f"Privileged pool size after fraud exclusion: {len(privileged_pool):,}")
    if len(privileged_pool) < PRIVILEGED_COUNT:
        raise ValueError(
            "Not enough privileged PaySim accounts after fraud exclusion: "
            f"need {PRIVILEGED_COUNT}, found {len(privileged_pool)}"
        )

    privileged = _take_ranked(
        privileged_pool,
        PRIVILEGED_COUNT,
        category="privileged",
        sort_columns=("total_txn_count", "total_amount", "nameOrig"),
        ascending=(False, False, True),
    )

    excluded_names = selected_fraud_names | set(privileged["nameOrig"])
    normal_pool = pool[
        (~pool["nameOrig"].isin(excluded_names))
        & (pool["fraud_count"] == 0)
        & (~pool["has_transfer_then_cashout"])
    ].copy()
    print(f"Normal pool size after fraud/privileged exclusion: {len(normal_pool):,}")
    if len(normal_pool) < NORMAL_COUNT:
        raise ValueError(
            "Not enough normal PaySim accounts after fraud/privileged exclusion: "
            f"need {NORMAL_COUNT}, found {len(normal_pool)}"
        )

    normal = normal_pool.sample(n=NORMAL_COUNT, random_state=42).copy()
    normal["category"] = "normal"

    selected = _flatten_selected_account_buckets(
        {
            "normal": normal,
            "privileged": privileged,
            "fraud_scenario": fraud,
        }
    )
    if selected["nameOrig"].duplicated().any():
        duplicates = selected.loc[selected["nameOrig"].duplicated(), "nameOrig"].tolist()
        raise ValueError(f"Selected duplicate PaySim accounts: {duplicates}")
    return {
        "normal": normal.reset_index(drop=True),
        "privileged": privileged.reset_index(drop=True),
        "fraud_scenario": fraud.reset_index(drop=True),
    }


def build_entity_mapping(
    selected_accounts: pd.DataFrame | dict[str, pd.DataFrame],
    cert_users: Sequence[str],
) -> dict[str, list[dict[str, Any]]]:
    """Build entity_mapping.json payload from selected PaySim accounts and CERT users."""

    selected_accounts = _flatten_selected_account_buckets(selected_accounts)
    if len(selected_accounts) != ENTITY_COUNT:
        raise ValueError(f"Need {ENTITY_COUNT} selected accounts, found {len(selected_accounts)}")

    normal_row_numbers = [
        row_number
        for row_number, category in enumerate(selected_accounts["category"], start=1)
        if category == "normal"
    ]
    if len(normal_row_numbers) < SERVICE_ACCOUNT_COUNT:
        raise ValueError(
            f"Need {SERVICE_ACCOUNT_COUNT} normal accounts for service accounts, "
            f"found {len(normal_row_numbers)}"
        )
    service_row_numbers = set(normal_row_numbers[:SERVICE_ACCOUNT_COUNT])
    human_count = ENTITY_COUNT - SERVICE_ACCOUNT_COUNT
    if len(cert_users) < human_count:
        raise ValueError(f"Need {human_count} CERT users for human entities, found {len(cert_users)}")

    cert_iter = iter(cert_users)
    entities: list[dict[str, Any]] = []

    for row_number, row in enumerate(selected_accounts.itertuples(index=False), start=1):
        entity_id = f"E{row_number:03d}"
        is_service_account = row_number in service_row_numbers
        category = str(row.category)

        if is_service_account:
            entity_type = "service_account"
            cert_user = None
            display_name = f"service_account_{entity_id.lower()}"
            role = "application_service"
        else:
            entity_type = "human"
            cert_user = next(cert_iter)
            display_name = cert_user
            role = _role_for_category(category, row_number)

        # Map onto the shared PrivilegeLevel enum (standard / elevated / admin).
        # "admin" roles (database_admin, system_admin) become ADMIN; other
        # privileged roles become ELEVATED. There is no "privileged" enum member.
        if category == "privileged":
            privilege_level = "admin" if "admin" in role else "elevated"
        else:
            privilege_level = "standard"
        department = DEPARTMENTS[(row_number - 1) % len(DEPARTMENTS)]

        entities.append(
            {
                "entity": {
                    "entity_id": entity_id,
                    "entity_type": entity_type,
                    "display_name": display_name,
                    "role": role,
                    "privilege_level": privilege_level,
                    "department": department,
                    "active": True,
                    "employment_end_date": None,
                    "hr_flag": None,
                },
                "source_ids": {
                    "cert": {
                        "user": cert_user,
                    },
                    "paysim": {
                        "nameOrig": row.nameOrig,
                    },
                    "telemetry": {
                        "device_ids": [f"DEV-{row_number:04d}"],
                        "ip_addresses": [f"10.42.0.{row_number}"],
                    },
                },
            }
        )

    return {"entities": entities}


def write_entity_mapping(payload: dict[str, Any], output_path: str) -> None:
    """Write the entity mapping JSON using stable indentation and key order."""

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def print_selection_summary(selected_accounts: pd.DataFrame, payload: dict[str, Any]) -> None:
    """Print category counts and selected PaySim activity for review."""

    selected_accounts = _flatten_selected_account_buckets(selected_accounts)
    entity_rows = []
    for entity, account in zip(payload["entities"], selected_accounts.itertuples(index=False)):
        entity_rows.append(
            {
                "entity_id": entity["entity"]["entity_id"],
                "category": account.category,
                "entity_type": entity["entity"]["entity_type"],
                "cert_user": entity["source_ids"]["cert"]["user"],
                "nameOrig": account.nameOrig,
                "role": entity["entity"]["role"],
                "privilege_level": entity["entity"]["privilege_level"],
                "total_txn_count": account.total_txn_count,
                "transfer_count": account.transfer_count,
                "cashout_count": account.cashout_count,
                "fraud_count": account.fraud_count,
                "has_transfer_then_cashout": account.has_transfer_then_cashout,
            }
        )

    summary = pd.DataFrame(entity_rows)
    print("Entity mapping category counts:")
    print(f"privileged: {(summary['category'] == 'privileged').sum()}")
    print(f"service_account: {(summary['entity_type'] == 'service_account').sum()}")
    print(f"fraud_scenario: {(summary['category'] == 'fraud_scenario').sum()}")
    print()
    print("Selected PaySim account sanity check:")
    print(summary.to_string(index=False))


def _find_transfer_then_cashout_accounts(
    paysim_df: pd.DataFrame,
    max_step_gap: int = 2,
) -> set[str]:
    """Return accounts with TRANSFER then CASH_OUT using vectorized PaySim-scale logic.

    This must stay vectorized because it runs against the full 6.36M-row PaySim file.
    """

    if max_step_gap < 0:
        raise ValueError("max_step_gap must be non-negative")

    events = paysim_df[paysim_df["type"].isin(["TRANSFER", "CASH_OUT"])].copy()
    if events.empty:
        return set()

    events = events.sort_values(["nameOrig", "step"], kind="mergesort")
    grouped = events.groupby("nameOrig", sort=False, observed=False)

    next_name_orig = grouped["nameOrig"].shift(-1)
    next_type = grouped["type"].shift(-1)
    next_step = grouped["step"].shift(-1)
    step_gap = next_step - events["step"]

    matches = events[
        (events["type"] == "TRANSFER")
        & (next_type == "CASH_OUT")
        & (next_name_orig == events["nameOrig"])
        & (step_gap >= 0)
        & (step_gap <= max_step_gap)
    ]
    return set(matches["nameOrig"].dropna().astype(str))


def _take_ranked(
    frame: pd.DataFrame,
    count: int,
    category: str,
    sort_columns: Sequence[str],
    ascending: Sequence[bool],
) -> pd.DataFrame:
    """Take the top ranked accounts for one selection category."""

    if len(frame) < count:
        raise ValueError(f"Need {count} {category} PaySim accounts, found {len(frame)}")

    selected = frame.sort_values(
        list(sort_columns),
        ascending=list(ascending),
        kind="mergesort",
    ).head(count).copy()
    selected["category"] = category
    return selected


def _flatten_selected_account_buckets(
    selected_accounts: pd.DataFrame | dict[str, pd.DataFrame],
) -> pd.DataFrame:
    """Return selected account buckets as the flat normal/privileged/fraud frame."""

    if isinstance(selected_accounts, pd.DataFrame):
        return selected_accounts.reset_index(drop=True).copy()

    frames = []
    for category in ("normal", "privileged", "fraud_scenario"):
        if category not in selected_accounts:
            raise ValueError(f"Missing selected account bucket: {category}")
        bucket = selected_accounts[category].copy()
        bucket["category"] = category
        frames.append(bucket)
    return pd.concat(frames, ignore_index=True)


def _role_for_category(category: str, row_number: int) -> str:
    """Return a deterministic role for a selected entity category."""

    if category == "privileged":
        return PRIVILEGED_ROLES[(row_number - 1) % len(PRIVILEGED_ROLES)]
    if category == "fraud_scenario":
        return FRAUD_SCENARIO_ROLES[(row_number - 1) % len(FRAUD_SCENARIO_ROLES)]
    return NORMAL_ROLES[(row_number - 1) % len(NORMAL_ROLES)]


def _default_project_path(relative_path: Path) -> Path:
    """Resolve a repository-relative path from this module's location."""

    return Path(__file__).resolve().parents[2] / relative_path


def main() -> None:
    """Generate entity_mapping.json from real CERT users and active PaySim accounts."""

    paysim_path = _default_project_path(DEFAULT_PAYSIM_RAW_DIR)
    cert_logon_path = _default_project_path(DEFAULT_CERT_LOGON_PATH)
    output_path = _default_project_path(DEFAULT_OUTPUT_PATH)
    mirror_output_path = _default_project_path(DEFAULT_MIRROR_OUTPUT_PATH)

    paysim_df = load_paysim(str(paysim_path))
    active_accounts = get_active_paysim_accounts(paysim_df)
    selected_account_buckets = select_paysim_accounts(active_accounts)

    cert_users = load_cert_users(str(cert_logon_path), limit=ENTITY_COUNT)
    payload = build_entity_mapping(selected_account_buckets, cert_users)
    print_selection_summary(selected_account_buckets, payload)
    write_entity_mapping(payload, str(output_path))
    print(f"Wrote entity mapping to {output_path}")
    if mirror_output_path != output_path:
        write_entity_mapping(payload, str(mirror_output_path))
        print(f"Wrote entity mapping mirror to {mirror_output_path}")


if __name__ == "__main__":
    main()
