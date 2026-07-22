"""Tests for CERT user-hour behavioral windows and causal baselines."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pyarrow.dataset as ds
import pytest

from ml.data_pipeline.cert_behavioral_windows import (
    CausalEventState,
    _attachment_stats,
    _baseline_profiles,
    _add_z_scores,
    aggregate_logon,
    build_behavioral_windows,
)


def _write_partition(
    root: Path, source: str, event_date: str, rows: list[dict[str, object]]
) -> None:
    path = root / "events" / f"source={source}" / f"event_date={event_date}"
    path.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_parquet(path / "part.parquet", index=False)


def _common(
    event_id: str,
    event_time: str,
    user: str,
    event_type: str,
    pc: str = "PC-0001",
) -> dict[str, object]:
    return {
        "event_id": event_id,
        "event_time": pd.Timestamp(event_time, tz="UTC"),
        "user_id": user,
        "pc_id": pc,
        "event_type": event_type,
    }


def _write_normalized_fixture(root: Path) -> None:
    root.mkdir()
    pd.DataFrame(
        [
            {
                "employee_name": "Admin User",
                "user_id": "AAA0001",
                "email": "admin@dtaa.com",
                "role": "ITAdmin",
                "projects": "P1;P2",
                "business_unit": "1",
                "functional_unit": "Admin",
                "department": "Security",
                "team": "Blue",
                "supervisor": "Boss",
                "start_date": "2009-01-01",
                "end_date": "2011-06-01",
            },
            {
                "employee_name": "Peer User",
                "user_id": "BBB0002",
                "email": "peer@dtaa.com",
                "role": "ITAdmin",
                "projects": "P1",
                "business_unit": "1",
                "functional_unit": "Admin",
                "department": "Security",
                "team": "Blue",
                "supervisor": "Boss",
                "start_date": "2009-01-01",
                "end_date": "2011-06-01",
            },
        ]
    ).to_parquet(root / "users.parquet", index=False)

    for source in ("logon", "device", "file", "email"):
        (root / "events" / f"source={source}").mkdir(parents=True)

    for day_number, logon_count in enumerate((1, 2, 3, 8), start=1):
        date = f"2010-01-0{day_number + 1}"
        logons: list[dict[str, object]] = []
        for user, count in (("AAA0001", logon_count), ("BBB0002", 1)):
            for offset in range(count):
                pc = (
                    "PC-0002"
                    if user == "AAA0001" and day_number >= 2
                    else "PC-0001"
                )
                logons.append(
                    _common(
                        f"L-{day_number}-{user}-{offset}",
                        f"{date} 09:00:{offset:02d}",
                        user,
                        "Logon",
                        pc,
                    )
                )
        _write_partition(root, "logon", date, logons)

        emails = []
        for user in ("AAA0001", "BBB0002"):
            row = _common(
                f"E-{day_number}-{user}",
                f"{date} 09:30:00",
                user,
                "Send",
            )
            row.update(
                {
                    "email_to": "outside@example.test",
                    "email_cc": "peer@dtaa.com",
                    "email_bcc": "",
                    "email_from": f"{user.lower()}@dtaa.com",
                    "email_size": 1000 + day_number,
                    "email_attachments": "C:\\x.txt(120);C:\\y.pdf(80)",
                }
            )
            emails.append(row)
        _write_partition(root, "email", date, emails)


def _read_variant(root: Path, variant: str) -> pd.DataFrame:
    return (
        ds.dataset(root / variant, format="parquet")
        .to_table()
        .to_pandas()
        .sort_values(["window_start", "user_id"], kind="mergesort")
        .reset_index(drop=True)
    )


def test_attachment_metadata_yields_real_counts_and_bytes() -> None:
    assert _attachment_stats(
        r"C:\a\one.doc(125);C:\b\two.pdf(375)"
    ) == (2, 500)
    assert _attachment_stats("") == (0, 0)


def test_logon_features_are_causal_and_sessions_are_matched() -> None:
    frame = pd.DataFrame(
        [
            _common(
                "L1", "2010-01-02 07:00:00", "AAA0001", "Logon", "PC-0001"
            ),
            _common(
                "L2", "2010-01-02 08:00:00", "AAA0001", "Logoff", "PC-0001"
            ),
            _common(
                "L3", "2010-01-02 09:00:00", "AAA0001", "Logon", "PC-0002"
            ),
        ]
    )
    frame["window_start"] = frame["event_time"].dt.floor("h")

    result = aggregate_logon(frame, CausalEventState())
    first = result[result["window_start"].dt.hour == 7].iloc[0]
    second = result[result["window_start"].dt.hour == 8].iloc[0]
    third = result[result["window_start"].dt.hour == 9].iloc[0]

    assert first["new_logon_pc_count"] == 1
    assert first["non_primary_logon_count"] == 0
    assert second["logon_session_minutes_mean"] == 60
    assert third["new_logon_pc_count"] == 1
    assert third["non_primary_logon_count"] == 1


def test_rolling_profiles_use_only_prior_days() -> None:
    summaries = pd.DataFrame(
        {
            "user_id": ["AAA0001"] * 4,
            "event_date": [
                "2010-01-02",
                "2010-01-03",
                "2010-01-04",
                "2010-01-05",
            ],
            "role": ["ITAdmin"] * 4,
            "logon_count__median": [1.0, 2.0, 3.0, 999.0],
            "logon_count__mad": [0.5, 0.5, 0.5, 0.5],
        }
    )

    profiles = _baseline_profiles(
        summaries,
        ["logon_count"],
        window_days=3,
        min_history_days=2,
    )

    assert pd.isna(profiles.loc[1, "logon_count__user_location"])
    assert profiles.loc[2, "logon_count__user_location"] == 1.5
    assert profiles.loc[3, "logon_count__user_location"] == 2.0
    assert profiles.loc[3, "logon_count__role_location"] == 2.0


def test_full_build_creates_separate_safe_variants(tmp_path: Path) -> None:
    input_root = tmp_path / "normalized"
    output_root = tmp_path / "features"
    manifest_path = tmp_path / "feature-manifest.json"
    _write_normalized_fixture(input_root)

    manifest = build_behavioral_windows(
        input_root=input_root,
        output_root=output_root,
        manifest_path=manifest_path,
        baseline_window_days=3,
        min_history_days=2,
    )
    base = _read_variant(output_root, "base")
    enhanced = _read_variant(output_root, "email_enhanced")

    assert manifest["ground_truth_used"] is False
    assert manifest["baseline"]["strictly_prior_days_only"] is True
    assert len(base) == len(enhanced) == 8
    assert "email_send_count" not in base.columns
    assert "email_send_count" in enhanced.columns
    assert enhanced["email_attachment_bytes"].eq(200).all()
    assert enhanced["email_external_recipient_ratio"].eq(0.5).all()

    first_admin = enhanced[
        (enhanced["user_id"] == "AAA0001")
        & (enhanced["event_date"] == "2010-01-02")
    ].iloc[0]
    second_admin = enhanced[
        (enhanced["user_id"] == "AAA0001")
        & (enhanced["event_date"] == "2010-01-03")
    ].iloc[0]
    assert first_admin["email_new_recipient_count"] == 2
    assert second_admin["email_new_recipient_count"] == 0
    assert first_admin["is_privileged_role"] == 1
    assert first_admin["project_count"] == 2
    assert second_admin["new_logon_pc_count"] == 1
    assert second_admin["non_primary_logon_count"] == 2

    forbidden = {
        "event_id",
        "pc_id",
        "file_name",
        "device_file_tree",
        "email_to",
        "email_from",
        "email_attachments",
        "content",
    }
    assert forbidden.isdisjoint(base.columns)
    assert forbidden.isdisjoint(enhanced.columns)
    assert "user_id" not in manifest["variants"]["base"]["model_feature_columns"]

    cold = enhanced[enhanced["event_date"].isin(["2010-01-02", "2010-01-03"])]
    assert cold["logon_count_user_robust_z"].eq(0).all()
    warm = enhanced[
        (enhanced["user_id"] == "AAA0001")
        & (enhanced["event_date"] == "2010-01-04")
    ]
    assert warm["logon_count_user_robust_z"].abs().gt(0).all()


def test_existing_output_is_never_overwritten(tmp_path: Path) -> None:
    input_root = tmp_path / "normalized"
    output_root = tmp_path / "features"
    _write_normalized_fixture(input_root)
    output_root.mkdir()

    with pytest.raises(ValueError, match="already exists"):
        build_behavioral_windows(
            input_root=input_root,
            output_root=output_root,
            manifest_path=tmp_path / "manifest.json",
        )


def test_constant_history_uses_scale_floor_for_new_spike() -> None:
    hourly = pd.DataFrame(
        {
            "user_id": ["AAA0001"],
            "event_date": ["2010-01-10"],
            "role": ["ITAdmin"],
            "logon_count": [5.0],
        }
    )
    profile = pd.DataFrame(
        {
            "user_id": ["AAA0001"],
            "event_date": ["2010-01-10"],
            "role": ["ITAdmin"],
            "user_history_days": [9],
            "role_history_days": [9],
            "logon_count__user_location": [0.0],
            "logon_count__user_scale": [0.0],
            "logon_count__role_location": [0.0],
            "logon_count__role_scale": [0.0],
        }
    )

    scored = _add_z_scores(hourly, profile, ["logon_count"], 7)

    assert scored.loc[0, "logon_count_user_robust_z"] == 5.0
    assert scored.loc[0, "logon_count_role_robust_z"] == 5.0


def test_repeated_builds_are_deterministic(tmp_path: Path) -> None:
    input_root = tmp_path / "normalized"
    _write_normalized_fixture(input_root)
    outputs = []
    for run in (1, 2):
        output_root = tmp_path / f"features-{run}"
        build_behavioral_windows(
            input_root=input_root,
            output_root=output_root,
            manifest_path=tmp_path / f"manifest-{run}.json",
            baseline_window_days=3,
            min_history_days=2,
        )
        outputs.append(
            (
                _read_variant(output_root, "base"),
                _read_variant(output_root, "email_enhanced"),
            )
        )

    pd.testing.assert_frame_equal(outputs[0][0], outputs[1][0])
    pd.testing.assert_frame_equal(outputs[0][1], outputs[1][1])
