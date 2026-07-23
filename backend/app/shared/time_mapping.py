"""Single documented synthetic clock for PaySim's relative step field."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

PAYSIM_STEP_ZERO_UTC = datetime(2010, 1, 1, tzinfo=timezone.utc)
PAYSIM_TIME_BASIS = "synthetic_step_mapping"
PAYSIM_TIME_MAPPING_DESCRIPTION = (
    "PaySim step 0 is mapped to 2010-01-01T00:00:00+00:00; each integer step adds one hour. "
    "This is a VaultWatch synthetic clock, not an observed banking timestamp."
)


def paysim_step_to_event_time(step: int) -> datetime:
    """Map PaySim's simulated hour counter to one fixed synthetic UTC clock."""
    return PAYSIM_STEP_ZERO_UTC + timedelta(hours=int(step))
