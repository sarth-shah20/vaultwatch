"""Tests for the quantum crypto-inventory + PQC-migration prioritization."""
from __future__ import annotations

from pathlib import Path

from backend.app.quantum_module.crypto_inventory.inventory import (
    DEFAULT_INVENTORY_PATH,
    build_report,
    classify_algorithm,
    load_inventory,
    score_asset,
)

ROOT = Path(__file__).resolve().parents[2]


def test_algorithm_classification() -> None:
    assert classify_algorithm("RSA-2048")["quantum_status"] == "quantum_vulnerable"
    assert classify_algorithm("ECDHE-RSA")["quantum_status"] == "quantum_vulnerable"
    assert classify_algorithm("ECDSA-P256")["quantum_status"] == "quantum_vulnerable"
    assert classify_algorithm("AES-256")["quantum_status"] == "quantum_safe"
    assert classify_algorithm("AES-128")["quantum_status"] == "quantum_weakened"
    assert classify_algorithm("ML-KEM-512")["quantum_status"] == "quantum_safe"
    assert classify_algorithm("HMAC-SHA256")["family"] == "hash"


def test_hndl_and_priority_scoring() -> None:
    critical = score_asset({"system": "PII", "crypto_algorithm": "RSA-2048", "purpose": "key_exchange",
                            "data_sensitivity": "restricted", "retention_years": 10})
    assert critical["priority_tier"] == "CRITICAL"
    assert critical["hndl_risk"] is True
    assert critical["recommended_pqc"] == "ML-KEM (Kyber)"

    session = score_asset({"system": "TLS", "crypto_algorithm": "ECDHE-RSA", "purpose": "key_exchange",
                           "data_sensitivity": "confidential", "retention_years": 1})
    assert session["hndl_risk"] is False  # short-lived -> not a harvest-now target

    safe = score_asset({"system": "lake", "crypto_algorithm": "AES-256", "purpose": "symmetric",
                        "data_sensitivity": "confidential", "retention_years": 10})
    assert safe["priority_tier"] == "LOW" and safe["hndl_risk"] is False


def test_signature_asset_recommends_ml_dsa() -> None:
    a = score_asset({"system": "sign", "crypto_algorithm": "ECDSA-P256", "purpose": "signature",
                     "data_sensitivity": "restricted", "retention_years": 7})
    assert a["recommended_pqc"] == "ML-DSA (Dilithium)"


def test_report_on_committed_inventory_is_ranked() -> None:
    report = build_report(load_inventory(ROOT / DEFAULT_INVENTORY_PATH))
    summary = report["summary"]
    assert summary["assets"] == 12
    assert summary["quantum_vulnerable"] >= 6
    assert summary["hndl_exposed"] >= 3
    scores = [a["priority_score"] for a in report["migration_priority"]]
    assert scores == sorted(scores, reverse=True)  # highest priority first
