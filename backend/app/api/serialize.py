"""Serialize the shared dataclasses (UnifiedIncident, RiskAssessment) to
JSON-able dicts — enums -> their value, datetimes -> ISO strings."""
from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import datetime
from enum import Enum
from typing import Any


def _clean(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(v) for v in value]
    return value


def to_dict(obj: Any) -> Any:
    """JSON-able dict for a dataclass instance (recurses into nested dataclasses)."""
    if is_dataclass(obj) and not isinstance(obj, type):
        return _clean(asdict(obj))
    return _clean(obj)
