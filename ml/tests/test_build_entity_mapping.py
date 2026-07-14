"""Tests for CERT-to-PaySim entity mapping generation."""

from __future__ import annotations

import pandas as pd

from ml.data_pipeline.build_entity_mapping import (
    ENTITY_COUNT,
    FRAUD_SCENARIO_COUNT,
    PRIVILEGED_COUNT,
    SERVICE_ACCOUNT_COUNT,
    build_entity_mapping,
    get_active_paysim_accounts,
    select_paysim_accounts,
)


def test_get_active_paysim_accounts_computes_counts_and_pattern() -> None:
    """Active account summary includes counts and transfer-then-cashout detection."""

    paysim = pd.DataFrame(
        {
            "step": [1, 2, 3, 10, 11, 12],
            "type": ["TRANSFER", "CASH_OUT", "PAYMENT", "TRANSFER", "PAYMENT", "CASH_OUT"],
            "amount": [100.0, 80.0, 10.0, 200.0, 5.0, 50.0],
            "nameOrig": ["C1", "C1", "C1", "C2", "C2", "C2"],
            "nameDest": ["C9", "C10", "M1", "C11", "M2", "C12"],
            "isFraud": [1, 1, 0, 0, 0, 0],
            "isFlaggedFraud": [0, 0, 0, 0, 0, 0],
        }
    )

    accounts = get_active_paysim_accounts(paysim, min_txn=1).set_index("nameOrig")

    assert accounts.loc["C1", "total_txn_count"] == 3
    assert accounts.loc["C1", "transfer_count"] == 1
    assert accounts.loc["C1", "cashout_count"] == 1
    assert accounts.loc["C1", "fraud_count"] == 2
    assert bool(accounts.loc["C1", "has_transfer_then_cashout"]) is True
    assert bool(accounts.loc["C2", "has_transfer_then_cashout"]) is True


def test_select_and_build_entity_mapping_preserves_requested_composition() -> None:
    """Selection produces 30 entities with service, privileged, and fraud groups."""

    selected = select_paysim_accounts(_active_account_pool())
    cert_users = [f"USR{i:04d}" for i in range(1, ENTITY_COUNT + 1)]
    payload = build_entity_mapping(selected, cert_users)
    selected_frame = pd.concat(selected.values(), ignore_index=True)

    entities = payload["entities"]
    assert len(entities) == ENTITY_COUNT
    assert entities[0]["entity"]["entity_id"] == "E001"
    assert entities[-1]["entity"]["entity_id"] == "E030"

    service_entities = [
        item for item in entities if item["entity"]["entity_type"] == "service_account"
    ]
    privileged_entities = [
        item for item in entities if item["entity"]["privilege_level"] == "privileged"
    ]

    assert len(service_entities) == SERVICE_ACCOUNT_COUNT
    assert len(privileged_entities) == PRIVILEGED_COUNT
    assert all(item["source_ids"]["cert"]["user"] is None for item in service_entities)
    assert all(isinstance(item["source_ids"]["paysim"]["nameOrig"], str) for item in entities)
    assert all(item["source_ids"]["telemetry"]["device_ids"] for item in entities)
    assert all(item["source_ids"]["telemetry"]["ip_addresses"] for item in entities)
    assert set(selected) == {"normal", "privileged", "fraud_scenario"}
    assert len(selected["normal"]) == 20
    assert len(selected["privileged"]) == PRIVILEGED_COUNT
    assert len(selected["fraud_scenario"]) == FRAUD_SCENARIO_COUNT
    assert selected_frame["category"].value_counts()["fraud_scenario"] == FRAUD_SCENARIO_COUNT


def _active_account_pool() -> pd.DataFrame:
    """Create enough active account summaries for deterministic selection."""

    rows = []
    for index in range(1, 41):
        rows.append(
            {
                "nameOrig": f"CLEAN{index:03d}",
                "total_txn_count": 5 + index,
                "total_amount": float(1000 + index * 10),
                "transfer_count": index % 3,
                "cashout_count": index % 4,
                "fraud_count": 0,
                "flagged_fraud_count": 0,
                "has_transfer_then_cashout": False,
            }
        )

    for index in range(1, 6):
        rows.append(
            {
                "nameOrig": f"FRAUD{index:03d}",
                "total_txn_count": 10 + index,
                "total_amount": float(5000 + index),
                "transfer_count": 1,
                "cashout_count": 1,
                "fraud_count": 1 if index % 2 else 0,
                "flagged_fraud_count": 0,
                "has_transfer_then_cashout": True,
            }
        )

    return pd.DataFrame(rows)
