"""Build leakage-safe CERT user-hour behavioral features and baselines.

Input is the normalized Step 1 bundle. Events are processed one calendar day at
a time. Novelty and session features use causal state, and robust baseline
features for a day use prior calendar days only.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import shutil
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path, PureWindowsPath
from typing import Any, Iterable

import numpy as np
import pandas as pd
import pyarrow.dataset as ds
import pyarrow.parquet as pq

FEATURE_SCHEMA_VERSION = "1.0"
DEFAULT_INPUT_ROOT = Path("data/processed/ps1/cert_events")
DEFAULT_OUTPUT_ROOT = Path("data/processed/ps1/cert_behavioral_windows")
DEFAULT_MANIFEST_PATH = Path(
    "data/manifests/ps1_cert_behavioral_features.json"
)
SOURCES = ("logon", "device", "file", "email")
INTERNAL_DOMAIN = "dtaa.com"
ATTACHMENT_BYTES_PATTERN = re.compile(r"\((\d+)\)(?:;|$)")
PRIVILEGED_ROLE_PATTERN = re.compile(
    r"(?:admin|manager|director|president|supervisor|security)", re.IGNORECASE
)

IDENTIFIER_COLUMNS = [
    "user_id",
    "window_start",
    "window_end",
    "event_time",
    "event_date",
]
CATEGORICAL_CONTEXT_COLUMNS = [
    "role",
    "business_unit",
    "functional_unit",
    "department",
    "team",
]
CONTEXT_FEATURES = [
    "is_weekend",
    "is_off_hours",
    "is_privileged_role",
    "project_count",
    "days_to_employment_end",
    "employment_end_proximity_30d",
    "event_count_total",
]
BASE_RAW_FEATURES = [
    "logon_event_count",
    "logon_count",
    "logoff_count",
    "unique_logon_pc_count",
    "new_logon_pc_count",
    "non_primary_logon_count",
    "non_primary_logon_ratio",
    "login_hour_surprise_mean",
    "logon_session_count",
    "logon_session_minutes_sum",
    "logon_session_minutes_mean",
    "logon_session_minutes_max",
    "device_event_count",
    "device_connect_count",
    "device_disconnect_count",
    "new_device_tree_count",
    "device_session_count",
    "device_session_minutes_sum",
    "device_session_minutes_mean",
    "device_session_minutes_max",
    "file_activity_count",
    "file_open_count",
    "file_write_count",
    "file_copy_count",
    "file_delete_count",
    "file_to_removable_count",
    "file_from_removable_count",
    "file_extension_count",
    "new_file_path_count",
]
EMAIL_RAW_FEATURES = [
    "email_event_count",
    "email_send_count",
    "email_view_count",
    "email_recipient_count",
    "email_external_recipient_count",
    "email_external_recipient_ratio",
    "email_unique_recipient_count",
    "email_new_recipient_count",
    "email_cc_bcc_recipient_count",
    "email_size_sum",
    "email_size_mean",
    "email_size_max",
    "email_attachment_count",
    "email_attachment_bytes",
    "email_off_hours_send_count",
    "email_new_sender_count",
    "email_external_sender_count",
    "email_off_hours_view_count",
]
BASELINE_BASE_FEATURES = [
    "logon_count",
    "unique_logon_pc_count",
    "new_logon_pc_count",
    "non_primary_logon_count",
    "login_hour_surprise_mean",
    "logon_session_minutes_mean",
    "device_connect_count",
    "new_device_tree_count",
    "device_session_minutes_mean",
    "file_activity_count",
    "file_to_removable_count",
    "new_file_path_count",
]
BASELINE_EMAIL_FEATURES = [
    "email_send_count",
    "email_view_count",
    "email_external_recipient_ratio",
    "email_unique_recipient_count",
    "email_new_recipient_count",
    "email_cc_bcc_recipient_count",
    "email_size_sum",
    "email_attachment_count",
    "email_attachment_bytes",
    "email_new_sender_count",
    "email_external_sender_count",
]


class BehavioralFeatureError(ValueError):
    """Raised when Step 2 input or output violates its contract."""


@dataclass
class CausalEventState:
    """History needed for features that must never inspect future events."""

    logon_pc_counts: dict[str, Counter[str]] = field(
        default_factory=lambda: defaultdict(Counter)
    )
    login_hour_counts: dict[str, Counter[int]] = field(
        default_factory=lambda: defaultdict(Counter)
    )
    open_logons: dict[tuple[str, str], pd.Timestamp] = field(
        default_factory=dict
    )
    seen_device_trees: dict[str, set[str]] = field(
        default_factory=lambda: defaultdict(set)
    )
    open_devices: dict[tuple[str, str], pd.Timestamp] = field(
        default_factory=dict
    )
    seen_file_paths: dict[str, set[str]] = field(
        default_factory=lambda: defaultdict(set)
    )
    seen_email_recipients: dict[str, set[str]] = field(
        default_factory=lambda: defaultdict(set)
    )
    seen_email_senders: dict[str, set[str]] = field(
        default_factory=lambda: defaultdict(set)
    )


def _empty_hourly() -> pd.DataFrame:
    return pd.DataFrame(columns=["user_id", "window_start"])


def _event_dates(events_root: Path) -> list[str]:
    dates: set[str] = set()
    for source in SOURCES:
        source_root = events_root / f"source={source}"
        if not source_root.is_dir():
            raise BehavioralFeatureError(
                f"Missing normalized source partition: {source_root}"
            )
        dates.update(
            path.name.removeprefix("event_date=")
            for path in source_root.glob("event_date=*")
            if path.is_dir()
        )
    if not dates:
        raise BehavioralFeatureError(f"No event partitions found in {events_root}")
    return sorted(dates)


def _read_day(events_root: Path, source: str, event_date: str) -> pd.DataFrame:
    path = events_root / f"source={source}" / f"event_date={event_date}"
    if not path.is_dir():
        return pd.DataFrame()
    frame = ds.dataset(path, format="parquet").to_table().to_pandas()
    if frame.empty:
        return frame
    frame = frame.sort_values(
        ["event_time", "event_id"], kind="mergesort"
    ).reset_index(drop=True)
    frame["window_start"] = frame["event_time"].dt.floor("h")
    return frame


def _safe_duration_minutes(
    start: pd.Timestamp | None,
    end: pd.Timestamp,
    maximum: float = 24 * 60,
) -> float:
    if start is None:
        return math.nan
    value = (end - start).total_seconds() / 60.0
    if value < 0 or value > maximum:
        return math.nan
    return value


def _group_last_event(frame: pd.DataFrame) -> pd.core.groupby.DataFrameGroupBy:
    return frame.groupby(["user_id", "window_start"], sort=False, observed=True)


def aggregate_logon(
    frame: pd.DataFrame, state: CausalEventState
) -> pd.DataFrame:
    if frame.empty:
        return _empty_hourly()

    is_logon: list[int] = []
    is_logoff: list[int] = []
    new_pc: list[int] = []
    non_primary: list[int] = []
    hour_surprise: list[float] = []
    session_minutes: list[float] = []

    for row in frame.itertuples(index=False):
        user = str(row.user_id)
        pc = str(row.pc_id)
        activity = str(row.event_type)
        timestamp = pd.Timestamp(row.event_time)
        if activity == "Logon":
            pc_counts = state.logon_pc_counts[user]
            hour_counts = state.login_hour_counts[user]
            total_hours = sum(hour_counts.values())
            surprise = -math.log(
                (hour_counts[timestamp.hour] + 1) / (total_hours + 24)
            )
            primary = (
                min(
                    (
                        pc_name
                        for pc_name, count in pc_counts.items()
                        if count == max(pc_counts.values())
                    ),
                    default=None,
                )
                if pc_counts
                else None
            )
            is_logon.append(1)
            is_logoff.append(0)
            new_pc.append(int(pc not in pc_counts))
            non_primary.append(int(primary is not None and pc != primary))
            hour_surprise.append(surprise)
            session_minutes.append(math.nan)
            state.open_logons[(user, pc)] = timestamp
            pc_counts[pc] += 1
            hour_counts[timestamp.hour] += 1
        else:
            is_logon.append(0)
            is_logoff.append(1)
            new_pc.append(0)
            non_primary.append(0)
            hour_surprise.append(math.nan)
            start = state.open_logons.pop((user, pc), None)
            session_minutes.append(_safe_duration_minutes(start, timestamp))

    work = frame.copy()
    work["_is_logon"] = is_logon
    work["_is_logoff"] = is_logoff
    work["_new_pc"] = new_pc
    work["_non_primary"] = non_primary
    work["_hour_surprise"] = hour_surprise
    work["_session_minutes"] = session_minutes
    grouped = _group_last_event(work)
    result = grouped.agg(
        logon_event_count=("event_id", "size"),
        logon_count=("_is_logon", "sum"),
        logoff_count=("_is_logoff", "sum"),
        unique_logon_pc_count=("pc_id", "nunique"),
        new_logon_pc_count=("_new_pc", "sum"),
        non_primary_logon_count=("_non_primary", "sum"),
        login_hour_surprise_mean=("_hour_surprise", "mean"),
        logon_session_count=("_session_minutes", "count"),
        logon_session_minutes_sum=("_session_minutes", "sum"),
        logon_session_minutes_mean=("_session_minutes", "mean"),
        logon_session_minutes_max=("_session_minutes", "max"),
        logon_last_event_time=("event_time", "max"),
    ).reset_index()
    result["non_primary_logon_ratio"] = _safe_ratio(
        result["non_primary_logon_count"], result["logon_count"]
    )
    return result


def aggregate_device(
    frame: pd.DataFrame, state: CausalEventState
) -> pd.DataFrame:
    if frame.empty:
        return _empty_hourly()

    connect: list[int] = []
    disconnect: list[int] = []
    new_tree: list[int] = []
    durations: list[float] = []
    for row in frame.itertuples(index=False):
        user = str(row.user_id)
        pc = str(row.pc_id)
        activity = str(row.event_type)
        tree = str(row.device_file_tree or "")
        timestamp = pd.Timestamp(row.event_time)
        if activity == "Connect":
            connect.append(1)
            disconnect.append(0)
            new_tree.append(int(bool(tree) and tree not in state.seen_device_trees[user]))
            if tree:
                state.seen_device_trees[user].add(tree)
            state.open_devices[(user, pc)] = timestamp
            durations.append(math.nan)
        else:
            connect.append(0)
            disconnect.append(1)
            new_tree.append(0)
            start = state.open_devices.pop((user, pc), None)
            durations.append(_safe_duration_minutes(start, timestamp))

    work = frame.copy()
    work["_connect"] = connect
    work["_disconnect"] = disconnect
    work["_new_tree"] = new_tree
    work["_session_minutes"] = durations
    return _group_last_event(work).agg(
        device_event_count=("event_id", "size"),
        device_connect_count=("_connect", "sum"),
        device_disconnect_count=("_disconnect", "sum"),
        new_device_tree_count=("_new_tree", "sum"),
        device_session_count=("_session_minutes", "count"),
        device_session_minutes_sum=("_session_minutes", "sum"),
        device_session_minutes_mean=("_session_minutes", "mean"),
        device_session_minutes_max=("_session_minutes", "max"),
        device_last_event_time=("event_time", "max"),
    ).reset_index()


def aggregate_file(
    frame: pd.DataFrame, state: CausalEventState
) -> pd.DataFrame:
    if frame.empty:
        return _empty_hourly()

    activity_names = frame["event_type"].astype(str)
    work = frame.copy()
    work["_open"] = activity_names.eq("File Open").astype("int8")
    work["_write"] = activity_names.eq("File Write").astype("int8")
    work["_copy"] = activity_names.eq("File Copy").astype("int8")
    work["_delete"] = activity_names.eq("File Delete").astype("int8")
    work["_to_removable"] = (
        work["to_removable_media"].fillna(False).astype(bool).astype("int8")
    )
    work["_from_removable"] = (
        work["from_removable_media"].fillna(False).astype(bool).astype("int8")
    )

    novelty: list[int] = []
    extensions: list[str] = []
    for row in frame.itertuples(index=False):
        user = str(row.user_id)
        path = str(row.file_name or "")
        novelty.append(
            int(bool(path) and path not in state.seen_file_paths[user])
        )
        if path:
            state.seen_file_paths[user].add(path)
        extensions.append(PureWindowsPath(path).suffix.lower())
    work["_new_path"] = novelty
    work["_extension"] = extensions
    grouped = _group_last_event(work)
    result = grouped.agg(
        file_activity_count=("event_id", "size"),
        file_open_count=("_open", "sum"),
        file_write_count=("_write", "sum"),
        file_copy_count=("_copy", "sum"),
        file_delete_count=("_delete", "sum"),
        file_to_removable_count=("_to_removable", "sum"),
        file_from_removable_count=("_from_removable", "sum"),
        file_extension_count=(
            "_extension",
            lambda values: values[values.ne("")].nunique(),
        ),
        new_file_path_count=("_new_path", "sum"),
        file_last_event_time=("event_time", "max"),
    ).reset_index()
    return result


def _addresses(*fields: object) -> list[str]:
    result: list[str] = []
    for field in fields:
        if field is None or pd.isna(field):
            continue
        result.extend(
            value.strip().lower()
            for value in str(field).split(";")
            if value.strip()
        )
    return result


def _is_external(address: str) -> bool:
    if "@" not in address:
        return False
    return address.rsplit("@", 1)[1].lower() != INTERNAL_DOMAIN


def _attachment_stats(value: object) -> tuple[int, int]:
    if value is None or pd.isna(value) or not str(value):
        return 0, 0
    text = str(value)
    sizes = [int(item) for item in ATTACHMENT_BYTES_PATTERN.findall(text)]
    entries = [item for item in text.split(";") if item]
    return len(entries), sum(sizes)


def aggregate_email(
    frame: pd.DataFrame, state: CausalEventState
) -> pd.DataFrame:
    if frame.empty:
        return _empty_hourly()

    metrics: dict[str, list[float | int]] = {
        "_send": [],
        "_view": [],
        "_recipients": [],
        "_external_recipients": [],
        "_new_recipients": [],
        "_cc_bcc": [],
        "_send_size": [],
        "_attachment_count": [],
        "_attachment_bytes": [],
        "_off_hours_send": [],
        "_new_sender": [],
        "_external_sender": [],
        "_off_hours_view": [],
    }
    hourly_recipients: dict[tuple[str, pd.Timestamp], set[str]] = defaultdict(set)

    for row in frame.itertuples(index=False):
        user = str(row.user_id)
        activity = str(row.event_type)
        timestamp = pd.Timestamp(row.event_time)
        off_hours = timestamp.hour < 8 or timestamp.hour >= 18
        values = {name: 0 for name in metrics}
        values["_send_size"] = math.nan
        if activity == "Send":
            recipients = _addresses(row.email_to, row.email_cc, row.email_bcc)
            unique_message_recipients = set(recipients)
            new = unique_message_recipients - state.seen_email_recipients[user]
            state.seen_email_recipients[user].update(unique_message_recipients)
            hourly_recipients[(user, timestamp.floor("h"))].update(
                unique_message_recipients
            )
            cc_bcc = _addresses(row.email_cc, row.email_bcc)
            attachment_count, attachment_bytes = _attachment_stats(
                row.email_attachments
            )
            values.update(
                {
                    "_send": 1,
                    "_recipients": len(recipients),
                    "_external_recipients": sum(
                        _is_external(address) for address in recipients
                    ),
                    "_new_recipients": len(new),
                    "_cc_bcc": len(cc_bcc),
                    "_send_size": int(row.email_size or 0),
                    "_attachment_count": attachment_count,
                    "_attachment_bytes": attachment_bytes,
                    "_off_hours_send": int(off_hours),
                }
            )
        else:
            sender = str(row.email_from or "").strip().lower()
            new_sender = bool(
                sender and sender not in state.seen_email_senders[user]
            )
            if sender:
                state.seen_email_senders[user].add(sender)
            values.update(
                {
                    "_view": 1,
                    "_new_sender": int(new_sender),
                    "_external_sender": int(
                        bool(sender) and _is_external(sender)
                    ),
                    "_off_hours_view": int(off_hours),
                }
            )
        for name in metrics:
            metrics[name].append(values[name])

    work = frame.copy()
    for name, values in metrics.items():
        work[name] = values
    result = _group_last_event(work).agg(
        email_event_count=("event_id", "size"),
        email_send_count=("_send", "sum"),
        email_view_count=("_view", "sum"),
        email_recipient_count=("_recipients", "sum"),
        email_external_recipient_count=("_external_recipients", "sum"),
        email_new_recipient_count=("_new_recipients", "sum"),
        email_cc_bcc_recipient_count=("_cc_bcc", "sum"),
        email_size_sum=("_send_size", "sum"),
        email_size_mean=("_send_size", "mean"),
        email_size_max=("_send_size", "max"),
        email_attachment_count=("_attachment_count", "sum"),
        email_attachment_bytes=("_attachment_bytes", "sum"),
        email_off_hours_send_count=("_off_hours_send", "sum"),
        email_new_sender_count=("_new_sender", "sum"),
        email_external_sender_count=("_external_sender", "sum"),
        email_off_hours_view_count=("_off_hours_view", "sum"),
        email_last_event_time=("event_time", "max"),
    ).reset_index()
    result["email_external_recipient_ratio"] = _safe_ratio(
        result["email_external_recipient_count"],
        result["email_recipient_count"],
    )
    result["email_unique_recipient_count"] = [
        len(hourly_recipients[(str(row.user_id), row.window_start)])
        for row in result.itertuples(index=False)
    ]
    return result


def _safe_ratio(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    return (
        numerator.astype(float)
        .div(denominator.replace(0, np.nan).astype(float))
        .fillna(0.0)
    )


def load_users(path: Path) -> pd.DataFrame:
    if not path.is_file():
        raise BehavioralFeatureError(f"Missing normalized users table: {path}")
    users = pd.read_parquet(path)
    required = {
        "user_id",
        "role",
        "projects",
        "business_unit",
        "functional_unit",
        "department",
        "team",
        "end_date",
    }
    missing = required - set(users.columns)
    if missing:
        raise BehavioralFeatureError(
            f"users.parquet is missing columns: {sorted(missing)}"
        )
    if users["user_id"].duplicated().any():
        raise BehavioralFeatureError("users.parquet has duplicate user_id values")
    users = users.copy()
    users["end_time"] = pd.to_datetime(
        users["end_date"], format="mixed", errors="coerce", utc=True
    )
    if users["end_time"].isna().any():
        raise BehavioralFeatureError("users.parquet has invalid end_date values")
    users["project_count"] = (
        users["projects"]
        .fillna("")
        .astype(str)
        .map(
            lambda value: len(
                [item for item in re.split(r"[;,|]", value) if item.strip()]
            )
        )
    )
    users["is_privileged_role"] = (
        users["role"]
        .fillna("")
        .astype(str)
        .str.contains(PRIVILEGED_ROLE_PATTERN)
        .astype("int8")
    )
    return users


def combine_hourly(
    frames: Iterable[pd.DataFrame],
    users: pd.DataFrame,
    event_date: str,
) -> pd.DataFrame:
    combined: pd.DataFrame | None = None
    for frame in frames:
        if frame.empty:
            continue
        combined = (
            frame
            if combined is None
            else combined.merge(
                frame,
                on=["user_id", "window_start"],
                how="outer",
                validate="one_to_one",
            )
        )
    if combined is None or combined.empty:
        return pd.DataFrame()

    user_context = users[
        [
            "user_id",
            "role",
            "business_unit",
            "functional_unit",
            "department",
            "team",
            "end_time",
            "project_count",
            "is_privileged_role",
        ]
    ]
    combined = combined.merge(
        user_context, on="user_id", how="left", validate="many_to_one"
    )
    if combined["role"].isna().any():
        unknown = combined.loc[combined["role"].isna(), "user_id"].unique()
        raise BehavioralFeatureError(
            f"Hourly windows contain unknown users: {unknown[:10].tolist()}"
        )

    last_event_columns = [
        name for name in combined.columns if name.endswith("_last_event_time")
    ]
    combined["event_time"] = combined[last_event_columns].max(axis=1)
    combined = combined.drop(columns=last_event_columns)
    numeric = BASE_RAW_FEATURES + EMAIL_RAW_FEATURES
    for column in numeric:
        if column not in combined:
            combined[column] = 0.0
        combined[column] = pd.to_numeric(
            combined[column], errors="coerce"
        ).fillna(0.0)

    combined["event_count_total"] = (
        combined["logon_event_count"]
        + combined["device_event_count"]
        + combined["file_activity_count"]
        + combined["email_event_count"]
    )
    combined["window_end"] = combined["window_start"] + pd.Timedelta(hours=1)
    combined["event_date"] = event_date
    combined["is_weekend"] = (
        combined["window_start"].dt.dayofweek >= 5
    ).astype("int8")
    combined["is_off_hours"] = (
        (combined["window_start"].dt.hour < 8)
        | (combined["window_start"].dt.hour >= 18)
    ).astype("int8")
    days_to_end = (
        combined["end_time"] - combined["window_start"]
    ).dt.total_seconds() / 86400.0
    combined["days_to_employment_end"] = days_to_end
    combined["employment_end_proximity_30d"] = (
        days_to_end.between(0, 30, inclusive="both")
    ).astype("int8")
    combined = combined.drop(columns=["end_time"])
    return combined.sort_values(
        ["window_start", "user_id"], kind="mergesort"
    ).reset_index(drop=True)


def _daily_summary(
    hourly: pd.DataFrame, features: list[str]
) -> pd.DataFrame:
    keys = ["user_id", "event_date", "role"]
    grouped = hourly.groupby(keys, sort=False, observed=True)
    medians = grouped[features].median().add_suffix("__median").reset_index()
    joined = hourly[keys + features].merge(
        medians, on=keys, how="left", validate="many_to_one"
    )
    deviations = pd.DataFrame(
        {
            feature: (
                joined[feature] - joined[f"{feature}__median"]
            ).abs()
            for feature in features
        }
    )
    deviations[keys] = joined[keys]
    mads = (
        deviations.groupby(keys, sort=False, observed=True)[features]
        .median()
        .add_suffix("__mad")
        .reset_index()
    )
    return medians.merge(mads, on=keys, validate="one_to_one")


def _write_day(frame: pd.DataFrame, root: Path, event_date: str) -> None:
    path = root / f"event_date={event_date}"
    path.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(
        path / f"part-{uuid.uuid4().hex}.parquet",
        index=False,
        compression="zstd",
    )


def build_hourly_and_daily_summaries(
    input_root: Path,
    staging_root: Path,
) -> tuple[list[str], dict[str, int]]:
    events_root = input_root / "events"
    users = load_users(input_root / "users.parquet")
    dates = _event_dates(events_root)
    state = CausalEventState()
    raw_root = staging_root / "hourly_raw"
    summary_root = staging_root / "daily_summaries"
    counts = {source: 0 for source in SOURCES}
    counts["windows"] = 0

    all_baseline_features = BASELINE_BASE_FEATURES + BASELINE_EMAIL_FEATURES
    for number, event_date in enumerate(dates, start=1):
        source_frames: list[pd.DataFrame] = []
        for source, aggregator in (
            ("logon", aggregate_logon),
            ("device", aggregate_device),
            ("file", aggregate_file),
            ("email", aggregate_email),
        ):
            events = _read_day(events_root, source, event_date)
            counts[source] += len(events)
            source_frames.append(aggregator(events, state))
        hourly = combine_hourly(source_frames, users, event_date)
        if hourly.empty:
            continue
        counts["windows"] += len(hourly)
        _write_day(hourly, raw_root, event_date)
        summary = _daily_summary(hourly, all_baseline_features)
        _write_day(summary, summary_root, event_date)
        if number == 1 or number % 25 == 0 or number == len(dates):
            print(
                f"Aggregated {number}/{len(dates)} days; "
                f"{counts['windows']:,} user-hour windows",
                flush=True,
            )
    return dates, counts


def _rolling_prior(
    values: pd.Series,
    groups: pd.Series,
    window_days: int,
    min_history_days: int,
    operation: str,
) -> pd.Series:
    shifted = values.groupby(groups, sort=False).shift(1)
    rolling = shifted.groupby(groups, sort=False).rolling(
        window_days, min_periods=min_history_days
    )
    if operation == "median":
        result = rolling.median()
    elif operation == "q25":
        result = rolling.quantile(0.25)
    elif operation == "q75":
        result = rolling.quantile(0.75)
    else:
        raise ValueError(operation)
    return result.reset_index(level=0, drop=True).sort_index()


def _baseline_profiles(
    summaries: pd.DataFrame,
    features: list[str],
    window_days: int,
    min_history_days: int,
) -> pd.DataFrame:
    summaries = summaries.sort_values(
        ["user_id", "event_date"], kind="mergesort"
    ).reset_index(drop=True)
    groups = summaries["user_id"]
    result = summaries[["user_id", "event_date", "role"]].copy()
    result["user_history_days"] = (
        summaries.groupby("user_id", sort=False).cumcount().clip(upper=window_days)
    )
    for feature in features:
        values = summaries[f"{feature}__median"].astype(float)
        within_mad = summaries[f"{feature}__mad"].astype(float)
        location = _rolling_prior(
            values, groups, window_days, min_history_days, "median"
        )
        q25 = _rolling_prior(
            values, groups, window_days, min_history_days, "q25"
        )
        q75 = _rolling_prior(
            values, groups, window_days, min_history_days, "q75"
        )
        within_scale = _rolling_prior(
            within_mad,
            groups,
            window_days,
            min_history_days,
            "median",
        ) * 1.4826
        between_scale = (q75 - q25) / 1.349
        result[f"{feature}__user_location"] = location
        result[f"{feature}__user_scale"] = pd.concat(
            [within_scale, between_scale], axis=1
        ).max(axis=1)

    role_daily = (
        summaries.groupby(["role", "event_date"], observed=True, sort=False)[
            [
                column
                for feature in features
                for column in (
                    f"{feature}__median",
                    f"{feature}__mad",
                )
            ]
        ]
        .median()
        .reset_index()
        .sort_values(["role", "event_date"], kind="mergesort")
        .reset_index(drop=True)
    )
    role_groups = role_daily["role"]
    role_profiles = role_daily[["role", "event_date"]].copy()
    role_profiles["role_history_days"] = (
        role_daily.groupby("role", sort=False)
        .cumcount()
        .clip(upper=window_days)
    )
    for feature in features:
        values = role_daily[f"{feature}__median"].astype(float)
        within_mad = role_daily[f"{feature}__mad"].astype(float)
        location = _rolling_prior(
            values, role_groups, window_days, min_history_days, "median"
        )
        q25 = _rolling_prior(
            values, role_groups, window_days, min_history_days, "q25"
        )
        q75 = _rolling_prior(
            values, role_groups, window_days, min_history_days, "q75"
        )
        within_scale = _rolling_prior(
            within_mad,
            role_groups,
            window_days,
            min_history_days,
            "median",
        ) * 1.4826
        between_scale = (q75 - q25) / 1.349
        role_profiles[f"{feature}__role_location"] = location
        role_profiles[f"{feature}__role_scale"] = pd.concat(
            [within_scale, between_scale], axis=1
        ).max(axis=1)
    return result.merge(
        role_profiles,
        on=["role", "event_date"],
        how="left",
        validate="many_to_one",
    )


def build_baseline_profiles(
    staging_root: Path,
    features: list[str],
    variant: str,
    window_days: int,
    min_history_days: int,
) -> None:
    summary_dataset = ds.dataset(
        staging_root / "daily_summaries",
        format="parquet",
    )
    columns = [
        "user_id",
        "event_date",
        "role",
        *[
            column
            for feature in features
            for column in (f"{feature}__median", f"{feature}__mad")
        ],
    ]
    summaries = summary_dataset.to_table(columns=columns).to_pandas()
    profiles = _baseline_profiles(
        summaries, features, window_days, min_history_days
    )
    profile_root = staging_root / "baseline_profiles" / variant
    for event_date, frame in profiles.groupby("event_date", sort=True):
        _write_day(frame, profile_root, str(event_date))
    print(
        f"Built {variant} prior-day baseline profiles for "
        f"{len(profiles):,} user-days",
        flush=True,
    )


def _read_partition(root: Path, event_date: str) -> pd.DataFrame:
    path = root / f"event_date={event_date}"
    if not path.is_dir():
        raise BehavioralFeatureError(f"Missing expected partition: {path}")
    return ds.dataset(path, format="parquet").to_table().to_pandas()


def _robust_scale_floor(feature: str) -> float:
    """Return a unit-aware floor for historically constant features."""

    if "ratio" in feature:
        return 0.05
    if "bytes" in feature or "size_sum" in feature:
        return 1024.0
    if "surprise" in feature:
        return 0.1
    return 1.0


def _add_z_scores(
    hourly: pd.DataFrame,
    profile: pd.DataFrame,
    features: list[str],
    min_history_days: int,
) -> pd.DataFrame:
    profile = profile.drop(
        columns=[
            column
            for column in ("user_history_days", "role_history_days")
            if column in hourly.columns
        ]
    )
    merged = hourly.merge(
        profile,
        on=["user_id", "event_date", "role"],
        how="left",
        validate="many_to_one",
    )
    for feature in features:
        for peer in ("user", "role"):
            scale = merged[f"{feature}__{peer}_scale"].astype(float)
            effective_scale = scale.clip(lower=_robust_scale_floor(feature))
            location = merged[f"{feature}__{peer}_location"].astype(float)
            history = merged[f"{peer}_history_days"].fillna(0)
            valid = (
                history.ge(min_history_days)
                & scale.notna()
                & location.notna()
            )
            z = pd.Series(0.0, index=merged.index)
            z.loc[valid] = (
                (merged.loc[valid, feature] - location.loc[valid])
                / effective_scale.loc[valid]
            )
            merged[f"{feature}_{peer}_robust_z"] = z.clip(-25.0, 25.0)
    drop = [
        column
        for column in merged.columns
        if column.endswith((
            "__user_location",
            "__user_scale",
            "__role_location",
            "__role_scale",
        ))
    ]
    return merged.drop(columns=drop)


def _model_columns(features: list[str]) -> list[str]:
    z_columns = [
        f"{feature}_{peer}_robust_z"
        for feature in features
        for peer in ("user", "role")
    ]
    return CONTEXT_FEATURES + BASE_RAW_FEATURES + z_columns


def materialize_variants(
    staging_root: Path,
    dates: list[str],
    min_history_days: int,
) -> tuple[int, list[str], list[str]]:
    base_model_columns = _model_columns(BASELINE_BASE_FEATURES)
    enhanced_model_columns = (
        CONTEXT_FEATURES
        + BASE_RAW_FEATURES
        + EMAIL_RAW_FEATURES
        + [
            f"{feature}_{peer}_robust_z"
            for feature in BASELINE_BASE_FEATURES + BASELINE_EMAIL_FEATURES
            for peer in ("user", "role")
        ]
    )
    metadata = IDENTIFIER_COLUMNS + CATEGORICAL_CONTEXT_COLUMNS
    total_rows = 0

    for number, event_date in enumerate(dates, start=1):
        hourly = _read_partition(
            staging_root / "hourly_raw", event_date
        )
        base_profile = _read_partition(
            staging_root / "baseline_profiles" / "base", event_date
        )
        email_profile = _read_partition(
            staging_root / "baseline_profiles" / "email", event_date
        )
        scored = _add_z_scores(
            hourly, base_profile, BASELINE_BASE_FEATURES, min_history_days
        )
        scored = _add_z_scores(
            scored, email_profile, BASELINE_EMAIL_FEATURES, min_history_days
        )
        base_columns = metadata + [
            "user_history_days",
            "role_history_days",
        ] + base_model_columns
        enhanced_columns = metadata + [
            "user_history_days",
            "role_history_days",
        ] + enhanced_model_columns
        _write_day(
            scored[base_columns],
            staging_root / "base",
            event_date,
        )
        _write_day(
            scored[enhanced_columns],
            staging_root / "email_enhanced",
            event_date,
        )
        total_rows += len(scored)
        if number == 1 or number % 25 == 0 or number == len(dates):
            print(
                f"Materialized {number}/{len(dates)} days; "
                f"{total_rows:,} feature windows",
                flush=True,
            )
    return total_rows, base_model_columns, enhanced_model_columns


def build_behavioral_windows(
    input_root: Path = DEFAULT_INPUT_ROOT,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    manifest_path: Path = DEFAULT_MANIFEST_PATH,
    *,
    baseline_window_days: int = 30,
    min_history_days: int = 7,
) -> dict[str, Any]:
    if baseline_window_days < 1:
        raise ValueError("baseline_window_days must be positive")
    if min_history_days < 1 or min_history_days > baseline_window_days:
        raise ValueError(
            "min_history_days must be between 1 and baseline_window_days"
        )
    if output_root.exists():
        raise BehavioralFeatureError(
            f"Output already exists; move it explicitly before rerunning: {output_root}"
        )
    staging_root = output_root.with_name(
        f".{output_root.name}.staging-{uuid.uuid4().hex}"
    )
    staging_root.mkdir(parents=True)
    try:
        dates, source_counts = build_hourly_and_daily_summaries(
            input_root, staging_root
        )
        build_baseline_profiles(
            staging_root,
            BASELINE_BASE_FEATURES,
            "base",
            baseline_window_days,
            min_history_days,
        )
        build_baseline_profiles(
            staging_root,
            BASELINE_EMAIL_FEATURES,
            "email",
            baseline_window_days,
            min_history_days,
        )
        total_rows, base_model_columns, enhanced_model_columns = (
            materialize_variants(staging_root, dates, min_history_days)
        )
        shutil.rmtree(staging_root / "baseline_profiles")
        output_root.parent.mkdir(parents=True, exist_ok=True)
        staging_root.rename(output_root)
    except Exception:
        if staging_root.exists():
            shutil.rmtree(staging_root)
        raise

    manifest = {
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "unlabeled": True,
        "ground_truth_used": False,
        "input_root": str(input_root),
        "output_root": str(output_root),
        "window": {
            "grain": "user-hour",
            "boundary": "UTC calendar hour",
            "active_windows_only": True,
        },
        "baseline": {
            "method": (
                f"prior-day {baseline_window_days}-day rolling median with max(within-day MAD, "
                "between-day IQR) robust scale"
            ),
            "window_days": baseline_window_days,
            "min_history_days": min_history_days,
            "strictly_prior_days_only": True,
            "cold_start_z_score": 0.0,
            "unit_aware_scale_floors": {
                "count_or_duration": 1.0,
                "ratio": 0.05,
                "hour_surprise": 0.1,
                "bytes_or_size_sum": 1024.0,
            },
            "z_score_clip": [-25.0, 25.0],
        },
        "counts": {
            **source_counts,
            "base_windows": total_rows,
            "email_enhanced_windows": total_rows,
        },
        "date_range": {"start": dates[0], "end": dates[-1]},
        "variants": {
            "base": {
                "path": str(output_root / "base"),
                "identifier_columns": IDENTIFIER_COLUMNS,
                "categorical_context_columns": CATEGORICAL_CONTEXT_COLUMNS,
                "model_feature_columns": base_model_columns,
            },
            "email_enhanced": {
                "path": str(output_root / "email_enhanced"),
                "identifier_columns": IDENTIFIER_COLUMNS,
                "categorical_context_columns": CATEGORICAL_CONTEXT_COLUMNS,
                "model_feature_columns": enhanced_model_columns,
            },
        },
        "intermediate": {
            "hourly_raw": str(output_root / "hourly_raw"),
            "daily_summaries": str(output_root / "daily_summaries"),
        },
        "privacy": {
            "excluded_from_outputs": [
                "event_id",
                "pc_id",
                "file_name",
                "device_file_tree",
                "email_to",
                "email_cc",
                "email_bcc",
                "email_from",
                "email_attachments",
                "file.content",
                "email.content",
            ],
            "user_id_is_identifier_not_model_feature": True,
        },
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-root", type=Path, default=DEFAULT_INPUT_ROOT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST_PATH)
    parser.add_argument("--baseline-window-days", type=int, default=30)
    parser.add_argument("--min-history-days", type=int, default=7)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    manifest = build_behavioral_windows(
        input_root=args.input_root,
        output_root=args.output_root,
        manifest_path=args.manifest,
        baseline_window_days=args.baseline_window_days,
        min_history_days=args.min_history_days,
    )
    print(
        json.dumps(
            {
                "windows": manifest["counts"]["base_windows"],
                "manifest": str(args.manifest),
            }
        )
    )


if __name__ == "__main__":
    main()
