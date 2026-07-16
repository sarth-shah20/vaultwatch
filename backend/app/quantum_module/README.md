# Quantum Module

Quantum-safe security for the PS1/PS2 pipeline. **Does NOT attempt real-time
HNDL/quantum-attack detection** (see docs/ARCHITECTURE.md "What NOT to build") —
it inventories quantum risk and provides PQC primitives.

## `crypto_inventory/` — quantum-risk inventory + PQC-migration prioritization
`inventory.py` classifies each system/data-flow's crypto (quantum_vulnerable /
weakened / safe), then scores a **PQC-migration priority** from
`algorithm_vulnerability x data_sensitivity x confidentiality_lifetime`, flags
**HNDL-exposed** assets (long-lived confidential data under RSA/ECC today), and
emits a ranked migration list with a recommended PQC replacement.

```
python3 backend/app/quantum_module/crypto_inventory/inventory.py \
    --inventory data/synthetic/crypto_inventory.json
```
Inputs: `data/synthetic/crypto_inventory.json` (synthetic bank inventory).
Output artifact: `data/synthetic/pqc_migration_report.json`.

## `pqc_utils/` — quantum-safe signing & key establishment
`pqc.py` wraps NIST-standardized PQC to protect what the pipeline produces:
- **ML-DSA (Dilithium)** — `sign_audit_record` / `verify_audit_record`: tamper-
  evident audit records / incident case files that survive quantum attacks on
  RSA/ECDSA.
- **ML-KEM (Kyber)** — `establish_key` / `recover_key`: quantum-safe key
  establishment for wrapping privileged credentials, replacing RSA/ECDH.

Backed by the pure-Python reference implementations `dilithium-py` / `kyber-py`
(`requirements.txt`). Correct per FIPS 204/203 but **reference implementations
(not constant-time / not production-hardened)** — appropriate for the demo, not
production. `pqc_available()` guards usage when the libraries are absent.
