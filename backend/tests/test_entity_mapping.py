from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.app.shared.entities import PrivilegeLevel
from backend.app.shared.entity_mapping import get_all_ids_for_entity, resolve_entity


MAPPING_PATH = Path(__file__).resolve().parents[2] / "data/synthetic/entity_mapping.json"


def _load_records() -> list[dict]:
    payload = json.loads(MAPPING_PATH.read_text(encoding="utf-8"))
    return payload["entities"]


ALL_RECORDS = _load_records()
RECORD_IDS = [record["entity"]["entity_id"] for record in ALL_RECORDS]


def test_mapping_has_expected_entity_count() -> None:
    assert len(ALL_RECORDS) == 30


@pytest.mark.parametrize("record", ALL_RECORDS, ids=RECORD_IDS)
def test_entity_ids_round_trip(record: dict) -> None:
    entity_id = record["entity"]["entity_id"]
    cert_user = record["source_ids"]["cert"]["user"]
    paysim_account = record["source_ids"]["paysim"]["nameOrig"]
    device_ids = record["source_ids"]["telemetry"]["device_ids"]
    ip_addresses = record["source_ids"]["telemetry"]["ip_addresses"]

    # PaySim + telemetry identifiers exist for every entity.
    assert resolve_entity(paysim_account, "paysim") == entity_id
    for device_id in device_ids:
        assert resolve_entity(device_id, "telemetry") == entity_id
    for ip_address in ip_addresses:
        assert resolve_entity(ip_address, "telemetry") == entity_id

    # CERT identity is only present for human entities; service accounts have none.
    if cert_user is not None:
        assert resolve_entity(cert_user, "cert") == entity_id

    assert get_all_ids_for_entity(entity_id) == {
        "entity_id": entity_id,
        "cert": {"user": cert_user},
        "paysim": {"nameOrig": paysim_account},
        "telemetry": {
            "device_ids": list(device_ids),
            "ip_addresses": list(ip_addresses),
        },
    }


def test_service_accounts_load_and_resolve_without_cert() -> None:
    # Regression: more than one service account has cert.user == null. The loader
    # must not treat multiple null CERT ids as a duplicate raw-id collision.
    service_accounts = [
        record
        for record in ALL_RECORDS
        if record["entity"]["entity_type"] == "service_account"
    ]
    assert len(service_accounts) >= 2
    for record in service_accounts:
        assert record["source_ids"]["cert"]["user"] is None
        entity_id = record["entity"]["entity_id"]
        paysim_account = record["source_ids"]["paysim"]["nameOrig"]
        assert resolve_entity(paysim_account, "paysim") == entity_id


def test_all_privilege_levels_are_valid_enum_members() -> None:
    # Regression: the generator once emitted "privileged", which is not a valid
    # PrivilegeLevel value and crashed deserialization on load.
    valid_values = {level.value for level in PrivilegeLevel}
    for record in ALL_RECORDS:
        assert record["entity"]["privilege_level"] in valid_values


def test_resolve_entity_rejects_unsupported_source() -> None:
    with pytest.raises(ValueError, match="Unsupported source"):
        resolve_entity("DNS1758", "unknown")


def test_resolve_entity_rejects_unknown_raw_id() -> None:
    with pytest.raises(ValueError, match="was not found"):
        resolve_entity("NOT-A-REAL-ID", "cert")


def test_get_all_ids_for_entity_rejects_unknown_entity() -> None:
    with pytest.raises(ValueError, match="Unknown entity_id"):
        get_all_ids_for_entity("E999")
