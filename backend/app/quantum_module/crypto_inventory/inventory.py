"""Quantum-risk crypto inventory + PQC-migration prioritization.

This is the honest, buildable answer to "quantum risk monitoring" (see
docs/ARCHITECTURE.md): it does NOT claim to detect passive harvest-now-decrypt-
later (HNDL) attacks in real time. Instead it inventories which systems/data
flows use quantum-vulnerable cryptography, scores each by (algorithm
vulnerability x data sensitivity x confidentiality lifetime), flags HNDL-exposed
assets, and produces a prioritized PQC-migration list.

HNDL intuition: data that must stay confidential for years AND is protected today
by quantum-vulnerable asymmetric crypto (RSA/ECC) is the classic target — an
adversary can harvest ciphertext now and decrypt it once a cryptographically
relevant quantum computer exists.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# (substring, family, quantum_status, risk_weight) — checked in priority order.
_FAMILY_RULES: list[tuple[str, str, str, float]] = [
    ("ML-KEM", "pqc", "quantum_safe", 0.0),
    ("KYBER", "pqc", "quantum_safe", 0.0),
    ("ML-DSA", "pqc", "quantum_safe", 0.0),
    ("DILITHIUM", "pqc", "quantum_safe", 0.0),
    ("SPHINCS", "pqc", "quantum_safe", 0.0),
    ("AES-256", "symmetric", "quantum_safe", 0.05),
    ("AES256", "symmetric", "quantum_safe", 0.05),
    ("AES-128", "symmetric", "quantum_weakened", 0.40),
    ("AES128", "symmetric", "quantum_weakened", 0.40),
    ("3DES", "symmetric", "legacy_broken", 0.90),
    ("MD5", "hash", "broken", 0.85),
    ("SHA-1", "hash", "broken", 0.80),
    ("HMAC", "hash", "quantum_adequate", 0.10),
    ("SHA-256", "hash", "quantum_adequate", 0.10),
    ("SHA256", "hash", "quantum_adequate", 0.10),
    ("RSA", "asymmetric", "quantum_vulnerable", 1.0),
    ("ECDSA", "asymmetric", "quantum_vulnerable", 1.0),
    ("ECDHE", "asymmetric", "quantum_vulnerable", 1.0),
    ("ECDH", "asymmetric", "quantum_vulnerable", 1.0),
    ("ECC", "asymmetric", "quantum_vulnerable", 1.0),
    ("DSA", "asymmetric", "quantum_vulnerable", 1.0),
    ("DIFFIE", "asymmetric", "quantum_vulnerable", 1.0),
    ("DH", "asymmetric", "quantum_vulnerable", 1.0),
]

SENSITIVITY_WEIGHT = {"public": 0.1, "internal": 0.4, "confidential": 0.7, "restricted": 1.0}

# purpose -> recommended NIST-standardized PQC replacement
_PQC_BY_PURPOSE = {
    "key_exchange": "ML-KEM (Kyber)",
    "signature": "ML-DSA (Dilithium)",
}


def classify_algorithm(algorithm: str) -> dict[str, Any]:
    upper = (algorithm or "").upper()
    for token, family, status, risk in _FAMILY_RULES:
        if token in upper:
            return {"family": family, "quantum_status": status, "risk_weight": risk}
    return {"family": "unknown", "quantum_status": "unknown", "risk_weight": 0.5}


def _tier(score: float) -> str:
    if score >= 0.7:
        return "CRITICAL"
    if score >= 0.45:
        return "HIGH"
    if score >= 0.2:
        return "MEDIUM"
    return "LOW"


def recommended_pqc(purpose: str, cls: dict) -> str:
    if cls["quantum_status"] in ("quantum_safe", "pqc", "quantum_adequate"):
        return "none (already adequate)"
    if cls["family"] == "symmetric":
        return "AES-256"
    return _PQC_BY_PURPOSE.get(purpose, "ML-KEM / ML-DSA")


def score_asset(asset: dict) -> dict[str, Any]:
    cls = classify_algorithm(asset["crypto_algorithm"])
    sensitivity = str(asset.get("data_sensitivity", "internal")).lower()
    sens_w = SENSITIVITY_WEIGHT.get(sensitivity, 0.4)
    retention = float(asset.get("retention_years", 0))
    retention_factor = min(retention / 10.0, 1.0)

    # priority grows with vulnerability, sensitivity, and confidentiality lifetime
    priority = cls["risk_weight"] * sens_w * (0.4 + 0.6 * retention_factor)
    priority = round(priority, 3)

    hndl_risk = (
        cls["quantum_status"] == "quantum_vulnerable"
        and sensitivity in ("confidential", "restricted")
        and retention >= 5
    )
    return {
        **{k: asset[k] for k in ("system", "data_flow", "crypto_algorithm", "purpose",
                                 "data_sensitivity", "retention_years") if k in asset},
        "quantum_status": cls["quantum_status"],
        "priority_score": priority,
        "priority_tier": _tier(priority),
        "hndl_risk": hndl_risk,
        "recommended_pqc": recommended_pqc(asset.get("purpose", ""), cls),
    }


def build_report(assets: list[dict]) -> dict[str, Any]:
    scored = sorted((score_asset(a) for a in assets), key=lambda x: x["priority_score"], reverse=True)
    tiers: dict[str, int] = {}
    for s in scored:
        tiers[s["priority_tier"]] = tiers.get(s["priority_tier"], 0) + 1
    return {
        "summary": {
            "assets": len(scored),
            "quantum_vulnerable": sum(1 for s in scored if s["quantum_status"] == "quantum_vulnerable"),
            "hndl_exposed": sum(1 for s in scored if s["hndl_risk"]),
            "by_tier": tiers,
        },
        "migration_priority": scored,
    }


def load_inventory(path: str | Path) -> list[dict]:
    return json.loads(Path(path).read_text(encoding="utf-8"))["assets"]


DEFAULT_INVENTORY_PATH = "data/synthetic/crypto_inventory.json"


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", default=DEFAULT_INVENTORY_PATH)
    args = parser.parse_args()
    report = build_report(load_inventory(args.inventory))
    print(json.dumps(report["summary"], indent=2))
    print("\nTop PQC-migration priorities:")
    for s in report["migration_priority"][:8]:
        flag = " [HNDL]" if s["hndl_risk"] else ""
        print(f"  {s['priority_tier']:8s} {s['priority_score']:.2f}  {s['system']} "
              f"({s['crypto_algorithm']}) -> {s['recommended_pqc']}{flag}")


if __name__ == "__main__":
    main()
