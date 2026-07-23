"""PS1 primary/shadow provider configuration for parallel cutover.

DTAA and CERT are two producers of the same ``ps1_behavioral`` domain. Shadow
results are comparison evidence only; callers must never ingest them beside a
primary result as cross-domain corroboration.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from backend.app.ps2_correlation.ps1_adapter import load_ps1_assessments
from backend.app.shared.assessment_schema import RiskAssessmentTransport
from backend.app.shared.entities import RiskAssessment

ProviderName = Literal["dtaa", "cert"]
ShadowProviderName = Literal["none", "dtaa", "cert"]


@dataclass(frozen=True)
class PS1ProviderConfig:
    primary: ProviderName = "cert"
    shadow: ShadowProviderName = "dtaa"

    @classmethod
    def from_env(cls) -> "PS1ProviderConfig":
        primary = os.getenv("PS1_PRIMARY_PROVIDER", "cert").lower()
        shadow = os.getenv("PS1_SHADOW_PROVIDER", "dtaa").lower()
        if primary not in {"dtaa", "cert"}:
            raise ValueError("PS1_PRIMARY_PROVIDER must be dtaa or cert")
        if shadow not in {"none", "dtaa", "cert"}:
            raise ValueError("PS1_SHADOW_PROVIDER must be none, dtaa, or cert")
        if shadow == primary:
            raise ValueError("PS1_SHADOW_PROVIDER must differ from PS1_PRIMARY_PROVIDER or be none")
        return cls(primary=primary, shadow=shadow)  # type: ignore[arg-type]


@dataclass(frozen=True)
class PS1ProviderRun:
    primary_provider: ProviderName
    primary_assessments: list[RiskAssessment]
    shadow_provider: ShadowProviderName
    shadow_assessments: list[RiskAssessment]

    def comparison_summary(self) -> dict:
        def summary(items: list[RiskAssessment]) -> dict:
            return {
                "alerts": len(items),
                "entities": len({item.entity_id for item in items}),
                "mean_score": round(sum(item.score for item in items) / len(items), 6) if items else 0.0,
                "with_reasons": sum(bool(item.reasons) for item in items),
                "sources": sorted({item.source for item in items}),
                "model_versions": sorted({item.model_version for item in items}),
            }
        return {
            "primary_provider": self.primary_provider,
            "shadow_provider": self.shadow_provider,
            "primary": summary(self.primary_assessments),
            "shadow": summary(self.shadow_assessments),
            "caveat": "Comparison is operational only: alert volume, explanation presence, and score distribution; not labeled detection performance.",
        }


def load_cert_assessments(root: str | Path = ".") -> list[RiskAssessment]:
    """Load generated CERT behavioral assessments for shadow/demo replay."""
    path = Path(root) / "data/synthetic/cert_demo_assessments.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [RiskAssessmentTransport.model_validate(item).to_entity() for item in payload["assessments"]]


def load_provider(provider: ProviderName, root: str | Path = ".") -> list[RiskAssessment]:
    if provider == "dtaa":
        return load_ps1_assessments(root=root)
    return load_cert_assessments(root=root)


def load_parallel_providers(root: str | Path = ".", config: PS1ProviderConfig | None = None) -> PS1ProviderRun:
    """Load primary + optional shadow without fusing them."""
    config = config or PS1ProviderConfig.from_env()
    primary = load_provider(config.primary, root)
    shadow = [] if config.shadow == "none" else load_provider(config.shadow, root)  # type: ignore[arg-type]
    return PS1ProviderRun(config.primary, primary, config.shadow, shadow)
