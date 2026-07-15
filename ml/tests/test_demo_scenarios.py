"""Tests for the curated PS1+PS2 demo scenarios (Step 3)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCENARIOS_PATH = ROOT / "data/synthetic/demo_scenarios.json"
MAPPING_PATH = ROOT / "data/synthetic/entity_mapping.json"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_demo_scenarios_parses_and_has_three() -> None:
    payload = _load(SCENARIOS_PATH)
    assert isinstance(payload, dict)
    assert isinstance(payload.get("scenarios"), list)
    assert len(payload["scenarios"]) == 3


def test_all_entity_ids_exist_in_entity_mapping() -> None:
    payload = _load(SCENARIOS_PATH)
    mapping = _load(MAPPING_PATH)
    known_ids = {e["entity"]["entity_id"] for e in mapping["entities"]}
    for scenario in payload["scenarios"]:
        assert scenario["entity_id"] in known_ids


def test_cert_user_and_paysim_account_match_the_mapping() -> None:
    payload = _load(SCENARIOS_PATH)
    mapping = {e["entity"]["entity_id"]: e for e in _load(MAPPING_PATH)["entities"]}
    for scenario in payload["scenarios"]:
        record = mapping[scenario["entity_id"]]
        assert scenario["cert_user"] == record["source_ids"]["cert"]["user"]
        assert scenario["paysim_account"] == record["source_ids"]["paysim"]["nameOrig"]


def test_every_scenario_labels_real_vs_injected() -> None:
    payload = _load(SCENARIOS_PATH)
    for scenario in payload["scenarios"]:
        cert = scenario["cert_event"]
        txn = scenario["paysim_transaction"]
        assert cert["source"] in {"real_cert", "injected"}
        assert isinstance(cert["injected"], bool)
        assert txn["source"] in {"real_paysim", "injected"}
        assert isinstance(txn["injected"], bool)
        # incident window alignment is explicitly flagged as curated
        assert scenario["incident_window"]["curated_alignment"] is True


def test_summary_counts_match_scenarios() -> None:
    payload = _load(SCENARIOS_PATH)
    scenarios = payload["scenarios"]
    summary = payload["summary"]
    assert summary["scenarios"] == len(scenarios)
    assert summary["real_cert_events"] == sum(1 for s in scenarios if not s["cert_event"]["injected"])
    assert summary["injected_cert_events"] == sum(1 for s in scenarios if s["cert_event"]["injected"])
    assert summary["real_paysim_txns"] == sum(1 for s in scenarios if not s["paysim_transaction"]["injected"])
