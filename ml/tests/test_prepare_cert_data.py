"""Tests for chunked CERT validation and normalization."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pyarrow.dataset as ds
import pytest

from ml.data_pipeline.prepare_cert_data import CertDataError, prepare_cert_data


def _write_fixture(
    root: Path, *, unknown_user: bool = False, duplicate_id: bool = False
) -> None:
    root.mkdir()
    pd.DataFrame(
        [[
            "Test User", "ABC0001", "test@dtaa.com", "ITAdmin", "", "1",
            "Admin", "Security", "Blue", "Boss", "2009-01-01", "2011-01-01",
        ]],
        columns=[
            "employee_name", "user_id", "email", "role", "projects",
            "business_unit", "functional_unit", "department", "team",
            "supervisor", "start_date", "end_date",
        ],
    ).to_csv(root / "users.csv", index=False)
    user = "XYZ9999" if unknown_user else "ABC0001"
    second_id = "L1" if duplicate_id else "L2"
    pd.DataFrame(
        [
            ["L1", "01/02/2010 07:00:00", user, "PC-0001", "Logon"],
            [second_id, "01/02/2010 08:00:00", user, "PC-0001", "Logoff"],
        ],
        columns=["id", "date", "user", "pc", "activity"],
    ).to_csv(root / "logon.csv", index=False)
    pd.DataFrame(
        [["D1", "01/02/2010 07:10:00", "ABC0001", "PC-0001", "R:\\", "Connect"]],
        columns=["id", "date", "user", "pc", "file_tree", "activity"],
    ).to_csv(root / "device.csv", index=False)
    pd.DataFrame(
        [[
            "F1", "01/02/2010 07:20:00", "ABC0001", "PC-0001",
            "R:\\a.txt", "File Write", True, False, "secret body",
        ]],
        columns=[
            "id", "date", "user", "pc", "filename", "activity",
            "to_removable_media", "from_removable_media", "content",
        ],
    ).to_csv(root / "file.csv", index=False)
    pd.DataFrame(
        [[
            "E1", "01/02/2010 07:30:00", "ABC0001", "PC-0001",
            "a@outside.test", "", "", "test@dtaa.com", "Send", 123,
            "a.txt", "private, quoted body",
        ]],
        columns=[
            "id", "date", "user", "pc", "to", "cc", "bcc", "from",
            "activity", "size", "attachments", "content",
        ],
    ).to_csv(root / "email.csv", index=False)


def test_prepare_cert_data_streams_and_excludes_content(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    output = tmp_path / "events"
    manifest_path = tmp_path / "manifest.json"
    _write_fixture(raw)

    manifest = prepare_cert_data(
        raw_root=raw,
        output_root=output,
        manifest_path=manifest_path,
        source_url="https://example.test/mirror",
        claimed_release="fixture",
        source_timezone_name="Asia/Kolkata",
        chunk_size=1,
        min_free_bytes=0,
    )

    assert manifest["validation_passed"] is True
    assert manifest["unlabeled"] is True
    assert manifest["ground_truth_used"] is False
    assert manifest["files"]["logon"]["validation"]["rows"] == 2
    saved = json.loads(manifest_path.read_text())
    assert saved["source"]["claimed_release"] == "fixture"

    dataset = ds.dataset(output / "events", format="parquet", partitioning="hive")
    table = dataset.to_table()
    assert table.num_rows == 5
    assert "content" not in table.column_names
    matching = table.filter(ds.field("event_id") == "L1")
    assert matching["event_time"][0].as_py().isoformat() == (
        "2010-01-02T01:30:00+00:00"
    )
    assert (output / "users.parquet").is_file()


def test_chunk_size_does_not_change_normalized_events(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    _write_fixture(raw)
    outputs = []
    for chunk_size in (1, 10):
        output = tmp_path / f"events-{chunk_size}"
        prepare_cert_data(
            raw_root=raw,
            output_root=output,
            manifest_path=tmp_path / f"manifest-{chunk_size}.json",
            source_timezone_name="UTC",
            chunk_size=chunk_size,
            fingerprint=False,
            min_free_bytes=0,
        )
        frame = ds.dataset(
            output / "events", format="parquet", partitioning="hive"
        ).to_table().to_pandas()
        outputs.append(
            frame.sort_values("event_id", kind="mergesort").reset_index(drop=True)
        )

    pd.testing.assert_frame_equal(outputs[0], outputs[1])


@pytest.mark.parametrize("case", ["unknown_user", "duplicate_id"])
def test_validation_rejects_identifier_contract_failures(
    tmp_path: Path, case: str
) -> None:
    raw = tmp_path / "raw"
    _write_fixture(raw, **{case: True})

    with pytest.raises(CertDataError, match="validation failed"):
        prepare_cert_data(
            raw_root=raw,
            output_root=tmp_path / "events",
            manifest_path=tmp_path / "manifest.json",
            normalize=False,
            fingerprint=False,
            chunk_size=1,
        )


def test_wrong_schema_fails_before_processing(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    _write_fixture(raw)
    pd.DataFrame({"wrong": [1]}).to_csv(raw / "email.csv", index=False)

    with pytest.raises(CertDataError, match="expected exactly"):
        prepare_cert_data(
            raw_root=raw,
            output_root=tmp_path / "events",
            manifest_path=tmp_path / "manifest.json",
            normalize=False,
            fingerprint=False,
        )
