from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.app.shared.entity_mapping import get_all_ids_for_entity, resolve_entity


MAPPING_PATH = Path(__file__).resolve().parents[2] / "data/synthetic/entity_mapping.json"


def _load_first_three_records() -> list[dict]:
    payload = json.loads(MAPPING_PATH.read_text(encoding="utf-8"))
    return payload["entities"][:3]


@pytest.mark.parametrize("record", _load_first_three_records())
def test_entity_ids_round_trip(record: dict) -> None:
    entity_id = record["entity"]["entity_id"]
    cert_user = record["source_ids"]["cert"]["user"]
    paysim_account = record["source_ids"]["paysim"]["nameOrig"]
    device_id = record["source_ids"]["telemetry"]["device_ids"][0]
    ip_address = record["source_ids"]["telemetry"]["ip_addresses"][0]

    assert resolve_entity(cert_user, "cert") == entity_id
    assert resolve_entity(paysim_account, "paysim") == entity_id
    assert resolve_entity(device_id, "telemetry") == entity_id
    assert resolve_entity(ip_address, "telemetry") == entity_id

    assert get_all_ids_for_entity(entity_id) == {
        "entity_id": entity_id,
        "cert": {"user": cert_user},
        "paysim": {"nameOrig": paysim_account},
        "telemetry": {
            "device_ids": [device_id],
            "ip_addresses": [ip_address],
        },
    }


def test_resolve_entity_rejects_unsupported_source() -> None:
    with pytest.raises(ValueError, match="Unsupported source"):
        resolve_entity("DNS1758", "unknown")


def test_resolve_entity_rejects_unknown_raw_id() -> None:
    with pytest.raises(ValueError, match="was not found"):
        resolve_entity("NOT-A-REAL-ID", "cert")


def test_get_all_ids_for_entity_rejects_unknown_entity() -> None:
    with pytest.raises(ValueError, match="Unknown entity_id"):
        get_all_ids_for_entity("E999")
