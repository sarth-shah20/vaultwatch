"""Feature engineering for the PaySim mobile-money fraud dataset."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd

REQUIRED_COLUMNS: tuple[str, ...] = (
    "step",
    "type",
    "amount",
    "nameOrig",
    "oldbalanceOrg",
    "newbalanceOrig",
    "nameDest",
    "oldbalanceDest",
    "newbalanceDest",
    "isFraud",
    "isFlaggedFraud",
)

DEFAULT_RAW_DIR = Path("data/raw/paysim")
DEFAULT_ENTITY_MAPPING_PATH = Path("data/synthetic/entity_mapping.json")
DEFAULT_OUTPUT_PATH = Path("data/processed/paysim_features.parquet")


def load_paysim(path: str) -> pd.DataFrame:
    """Load a PaySim CSV file or directory and apply basic dtype cleanup."""

    csv_path = _resolve_paysim_csv(Path(path))
    df = pd.read_csv(csv_path)
    _validate_required_columns(df.columns)

    df = df.copy()
    df["step"] = pd.to_numeric(df["step"], errors="raise").astype("int64")
    df["type"] = df["type"].astype("category")
    df["nameOrig"] = df["nameOrig"].astype("string")
    df["nameDest"] = df["nameDest"].astype("string")
    df["isFraud"] = pd.to_numeric(df["isFraud"], errors="raise").astype("int8")
    df["isFlaggedFraud"] = pd.to_numeric(df["isFlaggedFraud"], errors="raise").astype("int8")

    numeric_columns = (
        "amount",
        "oldbalanceOrg",
        "newbalanceOrig",
        "oldbalanceDest",
        "newbalanceDest",
    )
    for column in numeric_columns:
        df[column] = pd.to_numeric(df[column], errors="raise")

    return df


def load_entity_mapping(path: str) -> dict[str, str]:
    """Load entity_mapping.json as a PaySim nameOrig to synthetic entity_id map."""

    mapping_path = Path(path)
    with mapping_path.open("r", encoding="utf-8") as file:
        payload = json.load(file)

    entities = payload.get("entities", [])
    if not isinstance(entities, list):
        raise ValueError("entity_mapping.json must contain an entities list")

    entity_map: dict[str, str] = {}
    for entry in entities:
        if not isinstance(entry, dict):
            continue
        entity = entry.get("entity", {})
        source_ids = entry.get("source_ids", {})
        if not isinstance(entity, dict) or not isinstance(source_ids, dict):
            continue

        entity_id = entity.get("entity_id")
        paysim_ids = source_ids.get("paysim", {})
        if not isinstance(entity_id, str) or not isinstance(paysim_ids, dict):
            continue

        name_orig_values = paysim_ids.get("nameOrig")
        for name_orig in _as_string_values(name_orig_values):
            entity_map[name_orig] = entity_id

    return entity_map


def validate_entity_coverage(
    paysim_df: pd.DataFrame,
    entity_map: dict[str, str],
) -> pd.DataFrame:
    """Print and return PaySim activity coverage for mapped synthetic entities."""

    _validate_required_columns(paysim_df.columns)

    grouped = paysim_df.groupby("nameOrig", observed=False)
    total_counts = grouped.size()
    transfer_counts = paysim_df[paysim_df["type"].astype("string") == "TRANSFER"].groupby(
        "nameOrig",
        observed=False,
    ).size()
    cashout_counts = paysim_df[paysim_df["type"].astype("string") == "CASH_OUT"].groupby(
        "nameOrig",
        observed=False,
    ).size()

    rows = []
    for name_orig, entity_id in entity_map.items():
        total_txns = int(total_counts.get(name_orig, 0))
        rows.append(
            {
                "entity_id": entity_id,
                "nameOrig": name_orig,
                "total_txn_count": total_txns,
                "transfer_txn_count": int(transfer_counts.get(name_orig, 0)),
                "cashout_txn_count": int(cashout_counts.get(name_orig, 0)),
                "appears_as_nameOrig": total_txns > 0,
            }
        )

    coverage = pd.DataFrame(
        rows,
        columns=[
            "entity_id",
            "nameOrig",
            "total_txn_count",
            "transfer_txn_count",
            "cashout_txn_count",
            "appears_as_nameOrig",
        ],
    ).sort_values(["total_txn_count", "entity_id", "nameOrig"], kind="mergesort")

    print("PaySim mapped entity coverage:")
    if coverage.empty:
        print("No mapped PaySim nameOrig values found in the entity mapping.")
    else:
        print(coverage.to_string(index=False))

    missing_count = int((~coverage["appears_as_nameOrig"]).sum()) if not coverage.empty else 0
    if missing_count:
        print(f"WARNING: {missing_count} mapped PaySim account(s) do not appear as nameOrig.")

    low_activity = coverage[coverage["total_txn_count"] < 2] if not coverage.empty else coverage
    if not low_activity.empty:
        print(
            "WARNING: "
            f"{len(low_activity)} mapped PaySim account(s) have fewer than 2 transactions."
        )

    return coverage


def build_feature_set(
    df: pd.DataFrame,
    entity_map: dict[str, str],
    window: int = 24,
    transfer_cashout_window: int = 2,
) -> pd.DataFrame:
    """Return PaySim transactions with entity IDs and fraud-model features."""

    _validate_required_columns(df.columns)
    if window < 1:
        raise ValueError("window must be at least 1 step")
    if transfer_cashout_window < 1:
        raise ValueError("transfer_cashout_window must be at least 1 step")

    features = df.copy()
    features["_row_order"] = np.arange(len(features), dtype=np.int64)
    features = add_entity_ids(features, entity_map=entity_map)
    features = add_transaction_features(features)
    features = add_account_rolling_features(features, window=window)
    features = add_transfer_cashout_flag(
        features,
        transfer_cashout_window=transfer_cashout_window,
    )
    features = add_type_encoding(features)

    return features.drop(columns=["_row_order"])


def add_entity_ids(df: pd.DataFrame, entity_map: dict[str, str]) -> pd.DataFrame:
    """Add entity_id from the nameOrig mapping while preserving raw identifiers."""

    features = df.copy()
    features["entity_id"] = features["nameOrig"].map(entity_map)
    return features


def add_transaction_features(df: pd.DataFrame) -> pd.DataFrame:
    """Add row-level balance, destination, and calendar-style PaySim features."""

    features = df.copy()
    features["error_balance_orig"] = (
        features["oldbalanceOrg"] - features["amount"] - features["newbalanceOrig"]
    )
    features["error_balance_dest"] = (
        features["oldbalanceDest"] + features["amount"] - features["newbalanceDest"]
    )
    features["is_merchant_dest"] = features["nameDest"].astype("string").str.startswith("M").fillna(False)
    features["hour_of_day"] = (features["step"] % 24).astype("int64")
    features["day_index"] = (features["step"] // 24).astype("int64")
    return features


def add_type_encoding(df: pd.DataFrame) -> pd.DataFrame:
    """One-hot encode the PaySim transaction type while keeping the raw column."""

    features = df.copy()
    type_dummies = pd.get_dummies(features["type"], prefix="type", dtype="int8")
    return pd.concat([features, type_dummies], axis=1)


def add_account_rolling_features(df: pd.DataFrame, window: int = 24) -> pd.DataFrame:
    """Add trailing-window velocity, spend, fan-out, recency, and amount-ratio features."""

    start_time = time.time()

    if window < 1:
        raise ValueError("window must be at least 1 step")

    features = df.copy()
    row_order_column = "_row_order"
    if row_order_column not in features.columns:
        features[row_order_column] = np.arange(len(features), dtype=np.int64)

    work = features[["nameOrig", "step", "amount", "nameDest", row_order_column]].copy()
    work["_feature_row_id"] = np.arange(len(work), dtype=np.int64)
    work = work.sort_values(["nameOrig", "step", row_order_column], kind="mergesort")

    steps_since_previous = work.groupby("nameOrig", sort=False, observed=False)["step"].diff()

    current_rows = work[["_feature_row_id", "nameOrig", "step"]].rename(
        columns={"step": "current_step"}
    )
    history_rows = work[["nameOrig", "step", "amount", "nameDest"]].rename(
        columns={
            "step": "history_step",
            "amount": "history_amount",
            "nameDest": "history_nameDest",
        }
    )
    # PaySim nameOrig is extremely sparse, and pandas has no rolling nunique for this
    # step-window case. A self-merge by account keeps the whole operation vectorized
    # while producing only a few pairs per account for the real PaySim distribution.
    window_pairs = current_rows.merge(history_rows, on="nameOrig", how="left", sort=False)
    window_pairs = window_pairs[
        (window_pairs["history_step"] <= window_pairs["current_step"])
        & (window_pairs["history_step"] >= window_pairs["current_step"] - window)
    ]

    rolling_stats = window_pairs.groupby("_feature_row_id", sort=False).agg(
        orig_txn_count_trailing_window=("history_amount", "size"),
        orig_total_amount_trailing_window=("history_amount", "sum"),
        orig_unique_dest_trailing_window=("history_nameDest", "nunique"),
    )

    work = work.join(rolling_stats, on="_feature_row_id")
    work["orig_steps_since_prev_txn"] = steps_since_previous

    trailing_average = (
        work["orig_total_amount_trailing_window"]
        / work["orig_txn_count_trailing_window"]
    )
    work["amount_to_orig_trailing_avg_amount"] = np.where(
        trailing_average != 0,
        work["amount"] / trailing_average,
        1.0,
    )

    by_row_id = work.set_index("_feature_row_id")
    ordered_stats = by_row_id.loc[np.arange(len(features))]
    features["orig_txn_count_trailing_window"] = ordered_stats[
        "orig_txn_count_trailing_window"
    ].to_numpy(dtype=np.int64)
    features["orig_total_amount_trailing_window"] = ordered_stats[
        "orig_total_amount_trailing_window"
    ].to_numpy(dtype=np.float64)
    features["orig_unique_dest_trailing_window"] = ordered_stats[
        "orig_unique_dest_trailing_window"
    ].to_numpy(dtype=np.int64)
    features["orig_steps_since_prev_txn"] = ordered_stats[
        "orig_steps_since_prev_txn"
    ].to_numpy(dtype=np.float64)
    features["amount_to_orig_trailing_avg_amount"] = ordered_stats[
        "amount_to_orig_trailing_avg_amount"
    ].to_numpy(dtype=np.float64)
    print(f"add_account_rolling_features completed in {time.time() - start_time:.2f}s")
    return features


def add_transfer_cashout_flag(
    df: pd.DataFrame,
    transfer_cashout_window: int = 2,
) -> pd.DataFrame:
    """Flag CASH_OUT rows preceded by a TRANSFER from the same origin account."""

    if transfer_cashout_window < 1:
        raise ValueError("transfer_cashout_window must be at least 1 step")

    features = df.copy()
    row_order_column = "_row_order"
    if row_order_column not in features.columns:
        features[row_order_column] = np.arange(len(features), dtype=np.int64)

    # Vectorized equivalent of "for each CASH_OUT, was there a TRANSFER from the
    # same origin account within the trailing step window?". A merge_asof
    # (direction=backward) finds, per CASH_OUT, the most recent TRANSFER step for
    # that account; the row is flagged when the gap is within the window. This
    # stays O(n log n) and runs on the full 6.3M-row PaySim in seconds, whereas a
    # per-row Python loop does not.
    type_str = features["type"].astype("string")
    flags = pd.Series(False, index=features.index, dtype="bool")

    transfers = features.loc[type_str == "TRANSFER", ["nameOrig", "step"]].copy()
    cashouts = features.loc[type_str == "CASH_OUT", ["nameOrig", "step"]].copy()

    if not transfers.empty and not cashouts.empty:
        transfers["transfer_step"] = transfers["step"]
        transfers = transfers.sort_values("step", kind="mergesort")
        cashouts = cashouts.sort_values("step", kind="mergesort")

        matched = pd.merge_asof(
            cashouts,
            transfers[["nameOrig", "step", "transfer_step"]],
            on="step",
            by="nameOrig",
            direction="backward",
        )
        matched.index = cashouts.index  # restore original row indices (left order)

        gap = matched["step"] - matched["transfer_step"]
        flagged = matched["transfer_step"].notna() & (gap >= 0) & (gap <= transfer_cashout_window)
        flags.loc[flagged.index[flagged.to_numpy()]] = True

    features["is_transfer_then_cashout"] = flags
    return features


def _resolve_paysim_csv(path: Path) -> Path:
    """Resolve a PaySim CSV path, accepting either a file or a directory."""

    if path.is_file():
        return path
    if path.is_dir():
        csv_files = sorted(path.glob("*.csv"))
        if len(csv_files) == 1:
            return csv_files[0]
        if not csv_files:
            raise FileNotFoundError(f"No CSV files found in {path}")
        raise ValueError(f"Expected one CSV file in {path}, found {len(csv_files)}")
    raise FileNotFoundError(f"PaySim path does not exist: {path}")


def _as_string_values(value: Any) -> list[str]:
    """Normalize a mapping value that may be one string or a list of strings."""

    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str)]
    return []


def _validate_required_columns(columns: Iterable[str]) -> None:
    """Raise a clear error when the dataframe is missing PaySim columns."""

    present_columns = set(columns)
    missing_columns = [column for column in REQUIRED_COLUMNS if column not in present_columns]
    if missing_columns:
        missing = ", ".join(missing_columns)
        raise ValueError(f"Missing required PaySim columns: {missing}")


def _default_project_path(relative_path: Path) -> Path:
    """Resolve a repository-relative path from this module's location."""

    return Path(__file__).resolve().parents[2] / relative_path


def main() -> None:
    """Build the PaySim feature parquet from the default project data paths."""

    raw_input_path = _default_project_path(DEFAULT_RAW_DIR)
    entity_mapping_path = _default_project_path(DEFAULT_ENTITY_MAPPING_PATH)
    output_path = _default_project_path(DEFAULT_OUTPUT_PATH)

    paysim = load_paysim(str(raw_input_path))
    entity_map = load_entity_mapping(str(entity_mapping_path))
    validate_entity_coverage(paysim, entity_map)

    feature_set = build_feature_set(paysim, entity_map)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    feature_set.to_parquet(output_path, index=False)
    print(f"Wrote {len(feature_set):,} PaySim feature rows to {output_path}")


if __name__ == "__main__":
    main()
