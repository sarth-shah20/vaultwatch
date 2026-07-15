"""PS2 correlation engine: fuse per-domain RiskAssessments into UnifiedIncidents."""

from backend.app.ps2_correlation.correlation_engine.engine import (
    build_demo_incidents,
    correlate,
    decide_access,
    fuse_scores,
)

__all__ = ["correlate", "fuse_scores", "decide_access", "build_demo_incidents"]
