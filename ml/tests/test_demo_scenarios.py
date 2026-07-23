"""Tests for globally timed, model-derived CERT + PaySim demo scenarios."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCENARIOS_PATH = ROOT / "data/synthetic/demo_scenarios.json"
BRIDGE_PATH = ROOT / "data/synthetic/cert_paysim_global_demo_crosswalk.json"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_demo_scenarios_are_global_clock_model_pairs() -> None:
    payload = _load(SCENARIOS_PATH)
    assert payload["time_basis"] == "synthetic_step_mapping"
    assert payload["correlation_window_minutes"] == 120
    assert len(payload["scenarios"]) == 17


def test_scenario_identities_come_from_explicit_synthetic_bridge() -> None:
    bridge = _load(BRIDGE_PATH)
    pairs = {(item["entity_id"], item["cert_user"], item["paysim_nameOrig"]) for item in bridge["pairs"]}
    for scenario in _load(SCENARIOS_PATH)["scenarios"]:
        assert (scenario["entity_id"], scenario["cert_user"], scenario["paysim_account"]) in pairs


def test_every_scenario_is_real_model_alert_and_real_fraud_inside_global_window() -> None:
    for scenario in _load(SCENARIOS_PATH)["scenarios"]:
        cert = scenario["cert_assessment"]
        txn = scenario["paysim_transaction"]
        assert scenario["selection"].startswith("model-scored CERT alert")
        assert cert["risk_score"] >= 0.99
        assert txn["isFraud"] == 1
        assert txn["time_basis"] == "synthetic_step_mapping"
        cert_time = datetime.fromisoformat(cert["event_time"])
        paysim_time = datetime.fromisoformat(txn["event_time"])
        assert abs((cert_time - paysim_time).total_seconds()) <= 120 * 60


def test_summary_reports_generated_scenario_count() -> None:
    payload = _load(SCENARIOS_PATH)
    assert payload["summary"]["scenarios"] == len(payload["scenarios"])
