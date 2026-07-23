"""Documented temporal-correlation settings.

These values are operating policy, not learned/calibrated probabilities. In
particular, ``high`` and ``low`` describe cross-domain corroboration, never
statistical confidence.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CorrelationConfig:
    """Correlation policy shared by batch and persisted engines.

    ``window_minutes`` is intentionally 120: enough for investigation flow in
    synthetic demo while still rejecting unrelated activity days apart. Score
    cutoffs retain prior prototype policy until labelled calibration work.
    """

    window_minutes: int = 120
    fire_threshold: float = 0.5
    agreement_bonus: float = 0.3
    revoke_threshold: float = 0.9
    step_up_threshold: float = 0.7
    throttle_threshold: float = 0.4


DEFAULT_CORRELATION_CONFIG = CorrelationConfig()
