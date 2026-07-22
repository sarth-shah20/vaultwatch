"""Validate and normalize the unlabeled CERT activity dataset.

All activity CSVs are streamed. File and email body content is never copied to
the normalized dataset. Ground-truth answer files are out of scope by design.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
import sqlite3
import tempfile
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

MANIFEST_VERSION = "1.0"
NORMALIZED_SCHEMA_VERSION = "1.0"
DEFAULT_RAW_ROOT = Path("data/raw/cert_insider_threat")
DEFAULT_OUTPUT_ROOT = Path("data/processed/ps1/cert_events")
DEFAULT_MANIFEST_PATH = Path("data/manifests/ps1_cert_data_manifest.json")
DEFAULT_CHUNK_SIZE = 100_000
DEFAULT_MIN_FREE_BYTES = 2 * 1024**3
DATE_FORMAT = "%m/%d/%Y %H:%M:%S"

ACTIVITY_COLUMNS: dict[str, tuple[str, ...]] = {
    "logon": ("id", "date", "user", "pc", "activity"),
    "device": ("id", "date", "user", "pc", "file_tree", "activity"),
    "file": (
        "id", "date", "user", "pc", "filename", "activity",
        "to_removable_media", "from_removable_media", "content",
    ),
    "email": (
        "id", "date", "user", "pc", "to", "cc", "bcc", "from",
        "activity", "size", "attachments", "content",
    ),
}
USERS_COLUMNS = (
    "employee_name", "user_id", "email", "role", "projects", "business_unit",
    "functional_unit", "department", "team", "supervisor", "start_date", "end_date",
)
ALLOWED_ACTIVITIES = {
    "logon": {"Logon", "Logoff"},
    "device": {"Connect", "Disconnect"},
    "file": {"File Open", "File Write", "File Copy", "File Delete"},
    "email": {"Send", "View"},
}
USER_PATTERN = re.compile(r"^[A-Z]{3}\d{4}$")
PC_PATTERN = re.compile(r"^PC-\d{4}$")

NORMALIZED_SCHEMA = pa.schema(
    [
        ("event_id", pa.string()),
        ("event_time", pa.timestamp("us", tz="UTC")),
        ("user_id", pa.string()),
        ("pc_id", pa.string()),
        ("event_type", pa.string()),
        ("source", pa.string()),
        ("event_date", pa.string()),
        ("device_file_tree", pa.string()),
        ("file_name", pa.string()),
        ("to_removable_media", pa.bool_()),
        ("from_removable_media", pa.bool_()),
        ("email_to", pa.string()),
        ("email_cc", pa.string()),
        ("email_bcc", pa.string()),
        ("email_from", pa.string()),
        ("email_size", pa.int64()),
        ("email_attachments", pa.string()),
    ]
)


class CertDataError(ValueError):
    """Raised when raw CERT data violates the expected contract."""


@dataclass
class ValidationStats:
    rows: int = 0
    min_time: pd.Timestamp | None = None
    max_time: pd.Timestamp | None = None
    duplicate_event_ids: int = 0
    missing_required_values: int = 0
    unknown_users: set[str] = field(default_factory=set)
    invalid_user_ids: set[str] = field(default_factory=set)
    invalid_pc_ids: set[str] = field(default_factory=set)
    unexpected_activities: set[str] = field(default_factory=set)

    @property
    def passed(self) -> bool:
        return not any(
            (
                self.duplicate_event_ids,
                self.missing_required_values,
                self.unknown_users,
                self.invalid_user_ids,
                self.invalid_pc_ids,
                self.unexpected_activities,
            )
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "rows": self.rows,
            "date_range_utc": {
                "start": self.min_time.isoformat() if self.min_time is not None else None,
                "end": self.max_time.isoformat() if self.max_time is not None else None,
            },
            "duplicate_event_ids": self.duplicate_event_ids,
            "missing_required_values": self.missing_required_values,
            "unknown_user_count": len(self.unknown_users),
            "unknown_user_examples": sorted(self.unknown_users)[:20],
            "invalid_user_id_count": len(self.invalid_user_ids),
            "invalid_user_id_examples": sorted(self.invalid_user_ids)[:20],
            "invalid_pc_id_count": len(self.invalid_pc_ids),
            "invalid_pc_id_examples": sorted(self.invalid_pc_ids)[:20],
            "unexpected_activities": sorted(self.unexpected_activities),
            "passed": self.passed,
        }


class EventIdIndex:
    """Disk-backed exact uniqueness check, scoped to one source file."""

    def __init__(self) -> None:
        handle = tempfile.NamedTemporaryFile(
            prefix="cert-event-ids-", suffix=".sqlite3", delete=False
        )
        handle.close()
        self.path = Path(handle.name)
        self.connection = sqlite3.connect(self.path)
        self.connection.execute("PRAGMA journal_mode=OFF")
        self.connection.execute("PRAGMA synchronous=OFF")
        self.connection.execute(
            "CREATE TABLE ids (event_id TEXT PRIMARY KEY) WITHOUT ROWID"
        )

    def add(self, values: list[str]) -> int:
        before = self.connection.total_changes
        self.connection.executemany(
            "INSERT OR IGNORE INTO ids VALUES (?)", ((value,) for value in values)
        )
        self.connection.commit()
        inserted = self.connection.total_changes - before
        return len(values) - inserted

    def __enter__(self) -> "EventIdIndex":
        return self

    def __exit__(self, *_: object) -> None:
        self.connection.close()
        self.path.unlink(missing_ok=True)


def sha256_file(path: Path, block_size: int = 8 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        while block := file.read(block_size):
            digest.update(block)
    return digest.hexdigest()


def read_header(path: Path) -> list[str]:
    return list(pd.read_csv(path, nrows=0).columns)


def validate_header(path: Path, expected: tuple[str, ...]) -> list[str]:
    actual = read_header(path)
    if actual != list(expected):
        raise CertDataError(
            f"{path} has columns {actual}; expected exactly {list(expected)}"
        )
    return actual


def load_users(path: Path) -> tuple[pd.DataFrame, dict[str, Any]]:
    validate_header(path, USERS_COLUMNS)
    users = pd.read_csv(path, dtype="string", keep_default_na=False)
    missing_ids = int(users["user_id"].eq("").sum())
    duplicate_ids = int(users["user_id"].duplicated().sum())
    invalid_ids = sorted(
        {value for value in users["user_id"] if not USER_PATTERN.fullmatch(value)}
    )
    passed = not (missing_ids or duplicate_ids or invalid_ids)
    if not passed:
        raise CertDataError(
            "users.csv failed identifier validation: "
            f"missing={missing_ids}, duplicates={duplicate_ids}, invalid={len(invalid_ids)}"
        )
    return users, {
        "rows": len(users),
        "duplicate_user_ids": duplicate_ids,
        "missing_user_ids": missing_ids,
        "invalid_user_ids": invalid_ids[:20],
        "passed": passed,
    }


def parse_event_times(
    values: pd.Series, source_timezone: ZoneInfo, source: str
) -> pd.Series:
    parsed = pd.to_datetime(values, format=DATE_FORMAT, errors="coerce")
    invalid = int(parsed.isna().sum())
    if invalid:
        examples = values[parsed.isna()].astype(str).head(5).tolist()
        raise CertDataError(
            f"{source}.csv contains {invalid} invalid timestamps: {examples}"
        )
    try:
        localized = parsed.dt.tz_localize(
            source_timezone, ambiguous="raise", nonexistent="raise"
        )
    except (TypeError, ValueError) as error:
        raise CertDataError(
            f"{source}.csv has ambiguous/nonexistent local timestamps: {error}"
        ) from error
    return localized.dt.tz_convert("UTC")


def _parse_boolean(values: pd.Series, source: str) -> pd.Series:
    mapping = {"True": True, "False": False, "": pd.NA}
    text = values.fillna("").astype(str)
    invalid = sorted(set(text) - set(mapping))
    if invalid:
        raise CertDataError(
            f"{source}.csv has invalid boolean values: {invalid[:5]}"
        )
    return text.map(mapping).astype("boolean")


def normalize_chunk(
    chunk: pd.DataFrame, source: str, source_timezone: ZoneInfo
) -> pd.DataFrame:
    """Map one raw chunk to the shared event schema without body content."""

    times = parse_event_times(chunk["date"], source_timezone, source)
    normalized = pd.DataFrame(
        {
            "event_id": chunk["id"].astype("string"),
            "event_time": times,
            "user_id": chunk["user"].astype("string"),
            "pc_id": chunk["pc"].astype("string"),
            "event_type": chunk["activity"].astype("string"),
            "source": source,
            "event_date": times.dt.strftime("%Y-%m-%d"),
        }
    )
    if source == "device":
        normalized["device_file_tree"] = chunk["file_tree"].astype("string")
    elif source == "file":
        normalized["file_name"] = chunk["filename"].astype("string")
        normalized["to_removable_media"] = _parse_boolean(
            chunk["to_removable_media"], source
        )
        normalized["from_removable_media"] = _parse_boolean(
            chunk["from_removable_media"], source
        )
    elif source == "email":
        normalized["email_to"] = chunk["to"].astype("string")
        normalized["email_cc"] = chunk["cc"].astype("string")
        normalized["email_bcc"] = chunk["bcc"].astype("string")
        normalized["email_from"] = chunk["from"].astype("string")
        normalized["email_size"] = pd.to_numeric(
            chunk["size"], errors="raise"
        ).astype("Int64")
        normalized["email_attachments"] = chunk["attachments"].astype("string")
    return normalized


def validate_normalized_chunk(
    frame: pd.DataFrame,
    source: str,
    known_users: set[str],
    stats: ValidationStats,
) -> None:
    required = ["event_id", "event_time", "user_id", "pc_id", "event_type"]
    stats.rows += len(frame)
    stats.missing_required_values += int(frame[required].isna().sum().sum())
    stats.missing_required_values += sum(
        int(frame[column].astype("string").eq("").sum())
        for column in required
        if column != "event_time"
    )
    users = set(frame["user_id"].dropna().astype(str))
    stats.unknown_users.update(users - known_users)
    stats.invalid_user_ids.update(
        value for value in users if not USER_PATTERN.fullmatch(value)
    )
    pcs = set(frame["pc_id"].dropna().astype(str))
    stats.invalid_pc_ids.update(
        value for value in pcs if not PC_PATTERN.fullmatch(value)
    )
    stats.unexpected_activities.update(
        set(frame["event_type"].dropna().astype(str)) - ALLOWED_ACTIVITIES[source]
    )
    chunk_min = frame["event_time"].min()
    chunk_max = frame["event_time"].max()
    if stats.min_time is None or chunk_min < stats.min_time:
        stats.min_time = chunk_min
    if stats.max_time is None or chunk_max > stats.max_time:
        stats.max_time = chunk_max


def write_partitioned_chunk(frame: pd.DataFrame, output_root: Path) -> None:
    for field in NORMALIZED_SCHEMA:
        if field.name not in frame.columns:
            frame[field.name] = None
    table = pa.Table.from_pandas(
        frame, schema=NORMALIZED_SCHEMA, preserve_index=False
    )
    pq.write_to_dataset(
        table,
        root_path=output_root,
        partition_cols=["source", "event_date"],
        basename_template=f"part-{uuid.uuid4().hex}-{{i}}.parquet",
        compression="zstd",
    )


def validate_activity_file(
    path: Path,
    source: str,
    known_users: set[str],
    source_timezone: ZoneInfo,
    chunk_size: int,
    output_root: Path | None,
) -> ValidationStats:
    validate_header(path, ACTIVITY_COLUMNS[source])
    stats = ValidationStats()
    with EventIdIndex() as event_ids:
        chunks = pd.read_csv(
            path,
            dtype="string",
            keep_default_na=False,
            chunksize=chunk_size,
        )
        for chunk in chunks:
            normalized = normalize_chunk(chunk, source, source_timezone)
            validate_normalized_chunk(normalized, source, known_users, stats)
            stats.duplicate_event_ids += event_ids.add(
                normalized["event_id"].astype(str).tolist()
            )
            if output_root is not None:
                write_partitioned_chunk(normalized, output_root)
    return stats


def prepare_cert_data(
    raw_root: Path = DEFAULT_RAW_ROOT,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    manifest_path: Path = DEFAULT_MANIFEST_PATH,
    *,
    source_url: str = "not-recorded",
    claimed_release: str = "unknown-kaggle-mirror",
    source_description: str = "Kaggle-hosted CERT activity CSV mirror",
    source_timezone_name: str = "UTC",
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    normalize: bool = True,
    fingerprint: bool = True,
    min_free_bytes: int = DEFAULT_MIN_FREE_BYTES,
) -> dict[str, Any]:
    """Validate five inputs, optionally normalize, and write a manifest."""

    if chunk_size < 1:
        raise ValueError("chunk_size must be positive")
    try:
        source_timezone = ZoneInfo(source_timezone_name)
    except ZoneInfoNotFoundError as error:
        raise CertDataError(
            f"Unknown source timezone: {source_timezone_name}"
        ) from error

    paths = {
        name: raw_root / f"{name}.csv"
        for name in ("users", *ACTIVITY_COLUMNS)
    }
    missing = [str(path) for path in paths.values() if not path.is_file()]
    if missing:
        raise CertDataError(f"Missing required CERT files: {missing}")

    users, users_validation = load_users(paths["users"])
    known_users = set(users["user_id"].astype(str))
    staging_root: Path | None = None
    if normalize:
        if output_root.exists():
            raise CertDataError(
                "Output already exists; move it explicitly before rerunning: "
                f"{output_root}"
            )
        capacity_path = output_root.parent if output_root.parent.exists() else raw_root
        free_bytes = shutil.disk_usage(capacity_path).free
        if free_bytes < min_free_bytes:
            raise CertDataError(
                f"Only {free_bytes} bytes free; at least {min_free_bytes} required"
            )
        staging_root = output_root.with_name(
            f".{output_root.name}.staging-{uuid.uuid4().hex}"
        )
        staging_root.mkdir(parents=True)

    file_reports: dict[str, Any] = {}
    all_passed = True
    try:
        for source, path in paths.items():
            print(f"Validating {source}.csv ...", file=sys.stderr, flush=True)
            report: dict[str, Any] = {
                "path": str(path),
                "size_bytes": path.stat().st_size,
                "columns": read_header(path),
                "sha256": sha256_file(path) if fingerprint else None,
            }
            if source == "users":
                report["validation"] = users_validation
                report["passed"] = users_validation["passed"]
            else:
                stats = validate_activity_file(
                    path,
                    source,
                    known_users,
                    source_timezone,
                    chunk_size,
                    staging_root / "events" if staging_root is not None else None,
                )
                report["validation"] = stats.as_dict()
                report["passed"] = stats.passed
                all_passed = all_passed and stats.passed
            file_reports[source] = report
            print(f"Validated {source}.csv: {report["validation"]["rows"]:,} rows", file=sys.stderr, flush=True)

        if all_passed and staging_root is not None:
            users.to_parquet(
                staging_root / "users.parquet", index=False, compression="zstd"
            )
            output_root.parent.mkdir(parents=True, exist_ok=True)
            staging_root.rename(output_root)
            staging_root = None
    finally:
        if staging_root is not None and staging_root.exists():
            shutil.rmtree(staging_root)

    manifest = {
        "manifest_version": MANIFEST_VERSION,
        "normalized_schema_version": NORMALIZED_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "unlabeled": True,
        "ground_truth_used": False,
        "source": {
            "url": source_url,
            "claimed_release": claimed_release,
            "description": source_description,
            "simulated_local_timezone": source_timezone_name,
            "timestamp_normalization": (
                "localized using configured simulated timezone, then converted to UTC"
            ),
        },
        "raw_root": str(raw_root),
        "normalized_output": str(output_root) if normalize and all_passed else None,
        "normalization": {
            "enabled": normalize,
            "partition_columns": ["source", "event_date"] if normalize else [],
            "excluded_raw_columns": ["file.content", "email.content"],
            "schema": [
                {"name": field.name, "type": str(field.type)}
                for field in NORMALIZED_SCHEMA
            ],
        },
        "validation_passed": all_passed,
        "files": file_reports,
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    if not all_passed:
        raise CertDataError(
            f"CERT validation failed; inspect the manifest at {manifest_path}"
        )
    return manifest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-root", type=Path, default=DEFAULT_RAW_ROOT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST_PATH)
    parser.add_argument("--source-url", default="not-recorded")
    parser.add_argument("--claimed-release", default="unknown-kaggle-mirror")
    parser.add_argument(
        "--source-description",
        default="Kaggle-hosted CERT activity CSV mirror",
    )
    parser.add_argument("--source-timezone", default="UTC")
    parser.add_argument("--chunk-size", type=int, default=DEFAULT_CHUNK_SIZE)
    parser.add_argument(
        "--manifest-only",
        action="store_true",
        help="validate without writing Parquet",
    )
    parser.add_argument(
        "--skip-fingerprints",
        action="store_true",
        help="omit SHA-256 only for fast diagnostics",
    )
    parser.add_argument("--min-free-gib", type=float, default=2.0)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    manifest = prepare_cert_data(
        raw_root=args.raw_root,
        output_root=args.output_root,
        manifest_path=args.manifest,
        source_url=args.source_url,
        claimed_release=args.claimed_release,
        source_description=args.source_description,
        source_timezone_name=args.source_timezone,
        chunk_size=args.chunk_size,
        normalize=not args.manifest_only,
        fingerprint=not args.skip_fingerprints,
        min_free_bytes=int(args.min_free_gib * 1024**3),
    )
    print(
        json.dumps(
            {
                "validation_passed": manifest["validation_passed"],
                "manifest": str(args.manifest),
            }
        )
    )


if __name__ == "__main__":
    main()
