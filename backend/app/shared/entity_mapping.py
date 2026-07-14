"""Runtime entity resolution backed by the committed synthetic mapping artifact."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from backend.app.shared.entities import Entity, EntityType, PrivilegeLevel


MAPPING_PATH = Path(__file__).resolve().parents[3] / "data/synthetic/entity_mapping.json"
SUPPORTED_SOURCES = {"cert", "paysim", "telemetry"}


@dataclass
class _EntityMappingCache:
    entities: dict[str, dict]
    cert_index: dict[str, str]
    paysim_index: dict[str, str]
    telemetry_index: dict[str, str]


_CACHE: _EntityMappingCache | None = None


def _deserialize_entity(entity_payload: dict) -> Entity:
    employment_end_date = entity_payload.get("employment_end_date")
    parsed_end_date = (
        datetime.fromisoformat(employment_end_date) if employment_end_date else None
    )

    return Entity(
        entity_id=entity_payload["entity_id"],
        entity_type=EntityType(entity_payload["entity_type"]),
        display_name=entity_payload["display_name"],
        role=entity_payload.get("role"),
        privilege_level=PrivilegeLevel(entity_payload["privilege_level"]),
        department=entity_payload.get("department"),
        active=entity_payload.get("active", True),
        employment_end_date=parsed_end_date,
        hr_flag=entity_payload.get("hr_flag"),
    )


def _add_index_entry(index: dict[str, str], raw_id: str, entity_id: str, source: str) -> None:
    existing_entity_id = index.get(raw_id)
    if existing_entity_id and existing_entity_id != entity_id:
        raise ValueError(
            f"Duplicate {source} raw ID '{raw_id}' found for entities "
            f"'{existing_entity_id}' and '{entity_id}'."
        )

    index[raw_id] = entity_id


def _load_mapping() -> _EntityMappingCache:
    global _CACHE

    if _CACHE is not None:
        return _CACHE

    payload = json.loads(MAPPING_PATH.read_text(encoding="utf-8"))

    entities: dict[str, dict] = {}
    cert_index: dict[str, str] = {}
    paysim_index: dict[str, str] = {}
    telemetry_index: dict[str, str] = {}

    for record in payload["entities"]:
        entity = _deserialize_entity(record["entity"])
        entity_id = entity.entity_id
        source_ids = record["source_ids"]

        if entity_id in entities:
            raise ValueError(f"Duplicate entity_id '{entity_id}' found in mapping file.")

        cert_user = source_ids["cert"]["user"]
        paysim_account = source_ids["paysim"]["nameOrig"]
        device_ids = list(source_ids["telemetry"]["device_ids"])
        ip_addresses = list(source_ids["telemetry"]["ip_addresses"])

        # Service accounts have no CERT identity (cert_user is null); only index
        # real CERT user IDs so multiple null service accounts don't collide on
        # a shared None key.
        if cert_user is not None:
            _add_index_entry(cert_index, cert_user, entity_id, "cert")
        _add_index_entry(paysim_index, paysim_account, entity_id, "paysim")
        for raw_id in device_ids + ip_addresses:
            _add_index_entry(telemetry_index, raw_id, entity_id, "telemetry")

        entities[entity_id] = {
            "entity": entity,
            "source_ids": {
                "cert": {"user": cert_user},
                "paysim": {"nameOrig": paysim_account},
                "telemetry": {
                    "device_ids": device_ids,
                    "ip_addresses": ip_addresses,
                },
            },
        }

    _CACHE = _EntityMappingCache(
        entities=entities,
        cert_index=cert_index,
        paysim_index=paysim_index,
        telemetry_index=telemetry_index,
    )
    return _CACHE


def resolve_entity(raw_id: str, source: str) -> str:
    """Resolve a raw source-specific identifier to the canonical entity ID."""
    if source not in SUPPORTED_SOURCES:
        raise ValueError(
            f"Unsupported source '{source}'. Expected one of: {sorted(SUPPORTED_SOURCES)}."
        )

    cache = _load_mapping()
    index_by_source = {
        "cert": cache.cert_index,
        "paysim": cache.paysim_index,
        "telemetry": cache.telemetry_index,
    }
    entity_id = index_by_source[source].get(raw_id)

    if entity_id is None:
        raise ValueError(f"Raw ID '{raw_id}' was not found for source '{source}'.")

    return entity_id


def get_all_ids_for_entity(entity_id: str) -> dict:
    """Return all known raw IDs for a canonical entity ID."""
    cache = _load_mapping()
    record = cache.entities.get(entity_id)
    if record is None:
        raise ValueError(f"Unknown entity_id '{entity_id}'.")

    source_ids = record["source_ids"]
    return {
        "entity_id": entity_id,
        "cert": {"user": source_ids["cert"]["user"]},
        "paysim": {"nameOrig": source_ids["paysim"]["nameOrig"]},
        "telemetry": {
            "device_ids": list(source_ids["telemetry"]["device_ids"]),
            "ip_addresses": list(source_ids["telemetry"]["ip_addresses"]),
        },
    }
