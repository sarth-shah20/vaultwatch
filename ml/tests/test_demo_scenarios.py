"""Tests for the integrated PS1+PS2 demo scenarios (Step 3, Option 1)."""
from __future__ import annotations

import json
from pathlib import Path

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
    known_ids = {e["entity"]["entity_id"] for e in _load(MAPPING_PATH)["entities"]}
    for scenario in payload["scenarios"]:
        assert scenario["entity_id"] in known_ids


def test_ps1_user_and_paysim_account_match_the_mapping() -> None:
    mapping = {e["entity"]["entity_id"]: e for e in _load(MAPPING_PATH)["entities"]}
    for scenario in _load(SCENARIOS_PATH)["scenarios"]:
        record = mapping[scenario["entity_id"]]
        assert scenario["ps1_user"] == record["source_ids"]["ps1"]["user"]
        assert scenario["paysim_account"] == record["source_ids"]["paysim"]["nameOrig"]


def test_every_scenario_pairs_real_ps1_and_real_paysim() -> None:
    for scenario in _load(SCENARIOS_PATH)["scenarios"]:
        ps1 = scenario["ps1_event"]
        txn = scenario["paysim_transaction"]
        assert ps1["source"] == "real_ps1_isolation_forest" and ps1["injected"] is False
        assert 0.0 <= ps1["normalized_risk"] <= 1.0
        assert txn["source"] == "real_paysim" and txn["injected"] is False and txn["isFraud"] == 1
        assert scenario["incident_window"]["curated_alignment"] is True


def test_summary_reports_zero_injected() -> None:
    payload = _load(SCENARIOS_PATH)
    scenarios = payload["scenarios"]
    summary = payload["summary"]
    assert summary["scenarios"] == len(scenarios)
    assert summary["real_ps1_anomalies"] == sum(1 for s in scenarios if not s["ps1_event"]["injected"])
    assert summary["real_paysim_txns"] == sum(1 for s in scenarios if not s["paysim_transaction"]["injected"])
    assert summary["injected"] == 0
