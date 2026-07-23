"""Step-7 PS1 parallel cutover tests."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app.core.incident_store import IncidentStore
from backend.app.main import create_app
from backend.app.ps1_insider_threat.providers import PS1ProviderConfig, load_parallel_providers
from backend.app.ps2_correlation.correlation_engine import TemporalCorrelationStore
from backend.app.shared.entities import Reason, RiskAssessment

ROOT = Path(__file__).resolve().parents[2]


def test_default_parallel_cutover_keeps_dtaa_primary_and_cert_shadow(monkeypatch) -> None:
    monkeypatch.delenv("PS1_PRIMARY_PROVIDER", raising=False)
    monkeypatch.delenv("PS1_SHADOW_PROVIDER", raising=False)
    config = PS1ProviderConfig.from_env()
    assert (config.primary, config.shadow) == ("dtaa", "cert")
    run = load_parallel_providers(ROOT, config)
    assert run.primary_provider == "dtaa" and run.shadow_provider == "cert"
    assert run.primary_assessments and run.shadow_assessments
    assert all(item.domain == "ps1_behavioral" for item in [*run.primary_assessments, *run.shadow_assessments])
    assert run.comparison_summary()["caveat"].startswith("Comparison is operational")


def test_provider_config_rejects_invalid_or_same_shadow(monkeypatch) -> None:
    monkeypatch.setenv("PS1_PRIMARY_PROVIDER", "bogus")
    with pytest.raises(ValueError, match="PRIMARY"):
        PS1ProviderConfig.from_env()
    monkeypatch.setenv("PS1_PRIMARY_PROVIDER", "cert")
    monkeypatch.setenv("PS1_SHADOW_PROVIDER", "cert")
    with pytest.raises(ValueError, match="differ"):
        PS1ProviderConfig.from_env()


def test_same_domain_primary_and_shadow_do_not_corroborate() -> None:
    from backend.app.ps2_correlation.correlation_engine import TemporalCorrelationStore
    now = datetime(2031, 1, 1, tzinfo=timezone.utc)
    store = TemporalCorrelationStore()
    dtaa = RiskAssessment("CERT:USER", .9, [Reason("dtaa", "ps1_behavioral", .9)], assessment_id="dtaa", domain="ps1_behavioral", event_time=now)
    cert = RiskAssessment("CERT:USER", .95, [Reason("cert", "ps1_behavioral", .95)], assessment_id="cert", domain="ps1_behavioral", event_time=now + timedelta(minutes=1))
    store.ingest(dtaa)
    _, incidents = store.ingest(cert)
    assert incidents[0].confidence == "low"
    assert incidents[0].contributing_domains == ["ps1_behavioral"]
    assert [item.assessment_id for item in incidents[0].contributing_assessments] == ["cert"]


def test_provider_endpoint_exposes_resolved_cutover_policy(monkeypatch) -> None:
    monkeypatch.setenv("PS1_PRIMARY_PROVIDER", "cert")
    monkeypatch.setenv("PS1_SHADOW_PROVIDER", "dtaa")
    app = create_app(store=IncidentStore(":memory:"), temporal_store=TemporalCorrelationStore(), seed=False)
    payload = TestClient(app).get("/providers").json()
    assert payload == {"primary": "cert", "shadow": "dtaa", "domain": "ps1_behavioral", "shadow_counts_as_corroboration": False}
