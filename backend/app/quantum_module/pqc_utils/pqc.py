"""PQC utilities — quantum-safe signing + key establishment for VaultWatch.

Wraps NIST-standardized post-quantum crypto to protect the artifacts the PS1/PS2
pipeline produces so they resist harvest-now-decrypt-later exposure:
- ML-DSA (Dilithium) signs audit records / incident case files -> tamper-evidence
  that survives quantum attacks on RSA/ECDSA.
- ML-KEM (Kyber) establishes a shared key for wrapping privileged credentials,
  replacing quantum-vulnerable RSA/ECDH key exchange.

Backed by the pure-Python reference implementations `dilithium-py` / `kyber-py`.
These are correct per FIPS 204 / 203 but are REFERENCE implementations (not
constant-time, not production-hardened) — appropriate for the demo, not prod.
"""
from __future__ import annotations

import json
from typing import Any

try:
    from dilithium_py.ml_dsa import ML_DSA_44
    from kyber_py.ml_kem import ML_KEM_512
    _PQC_AVAILABLE = True
except Exception:  # pragma: no cover - import guard
    _PQC_AVAILABLE = False

ML_DSA_ALG = "ML-DSA-44"
ML_KEM_ALG = "ML-KEM-512"


def pqc_available() -> bool:
    return _PQC_AVAILABLE


def _require() -> None:
    if not _PQC_AVAILABLE:
        raise RuntimeError("PQC libraries unavailable; `pip install dilithium-py kyber-py`.")


def _canonical(record: Any) -> bytes:
    return json.dumps(record, sort_keys=True, separators=(",", ":")).encode("utf-8")


# --- ML-DSA: sign / verify audit records ---------------------------------------

def generate_signing_keypair() -> tuple[bytes, bytes]:
    """Return (public_key, secret_key) for ML-DSA signing."""
    _require()
    return ML_DSA_44.keygen()


def sign_audit_record(record: dict, secret_key: bytes) -> dict:
    """Sign a record with ML-DSA; returns the record plus a hex signature."""
    _require()
    signature = ML_DSA_44.sign(secret_key, _canonical(record))
    return {"algorithm": ML_DSA_ALG, "record": record, "signature": signature.hex()}


def verify_audit_record(signed: dict, public_key: bytes) -> bool:
    """Verify a signed record (as produced by sign_audit_record)."""
    _require()
    return bool(
        ML_DSA_44.verify(public_key, _canonical(signed["record"]), bytes.fromhex(signed["signature"]))
    )


# --- ML-KEM: key establishment for credential protection -----------------------

def generate_kem_keypair() -> tuple[bytes, bytes]:
    """Return (encapsulation_key, decapsulation_key) for ML-KEM."""
    _require()
    return ML_KEM_512.keygen()


def establish_key(encapsulation_key: bytes) -> tuple[bytes, bytes]:
    """Sender side: return (shared_key, ciphertext). The shared_key would seed an
    AEAD to wrap a credential; the ciphertext is sent to the holder."""
    _require()
    return ML_KEM_512.encaps(encapsulation_key)


def recover_key(decapsulation_key: bytes, ciphertext: bytes) -> bytes:
    """Receiver side: recover the same shared_key from the ciphertext."""
    _require()
    return ML_KEM_512.decaps(decapsulation_key, ciphertext)
