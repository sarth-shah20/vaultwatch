"""Tests for the PQC utilities (real ML-DSA / ML-KEM round-trips)."""
from __future__ import annotations

import pytest

from backend.app.quantum_module.pqc_utils.pqc import (
    establish_key,
    generate_kem_keypair,
    generate_signing_keypair,
    pqc_available,
    recover_key,
    sign_audit_record,
    verify_audit_record,
)

pytestmark = pytest.mark.skipif(not pqc_available(), reason="PQC libraries not installed")


def test_ml_dsa_sign_verify_and_tamper_detection() -> None:
    public_key, secret_key = generate_signing_keypair()
    record = {"incident_id": "INC-E028", "entity_id": "E028", "combined_score": 0.9481}

    signed = sign_audit_record(record, secret_key)
    assert signed["algorithm"] == "ML-DSA-44"
    assert verify_audit_record(signed, public_key) is True

    # tampering with the record invalidates the signature
    tampered = {**signed, "record": {**record, "combined_score": 0.10}}
    assert verify_audit_record(tampered, public_key) is False


def test_ml_kem_shared_key_matches() -> None:
    encapsulation_key, decapsulation_key = generate_kem_keypair()
    shared_key, ciphertext = establish_key(encapsulation_key)
    assert recover_key(decapsulation_key, ciphertext) == shared_key
    assert len(shared_key) == 32
