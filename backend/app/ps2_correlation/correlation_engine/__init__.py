"""PS2 correlation engine: fuse per-domain RiskAssessments into UnifiedIncidents."""

from backend.app.ps2_correlation.correlation_engine.config import CorrelationConfig
from backend.app.ps2_correlation.correlation_engine.engine import (
    build_demo_incidents, correlate, correlate_window, decide_access, fuse_scores,
)
from backend.app.ps2_correlation.correlation_engine.store import TemporalCorrelationStore

__all__ = [
    "correlate", "correlate_window", "fuse_scores", "decide_access",
    "build_demo_incidents", "CorrelationConfig", "TemporalCorrelationStore",
]
