"""Alert lifecycle for UnifiedIncidents (FEATURES.md PS2 item 7).

A validated state machine over the shared IncidentStatus states:
    new -> escalated -> acknowledged -> dismissed
Analyst actions drive transitions; dismissals carry a reason and feed the
suppression/feedback loop in the incident store.
"""
from __future__ import annotations

from backend.app.shared.entities import IncidentStatus

# Allowed target states from each current state.
ALLOWED_TRANSITIONS: dict[IncidentStatus, set[IncidentStatus]] = {
    IncidentStatus.NEW: {IncidentStatus.ESCALATED, IncidentStatus.ACKNOWLEDGED, IncidentStatus.DISMISSED},
    IncidentStatus.ESCALATED: {IncidentStatus.ACKNOWLEDGED, IncidentStatus.DISMISSED},
    IncidentStatus.ACKNOWLEDGED: {IncidentStatus.ESCALATED, IncidentStatus.DISMISSED},
    IncidentStatus.DISMISSED: set(),  # terminal
}

# Analyst action -> target state.
ACTION_TO_STATUS: dict[str, IncidentStatus] = {
    "escalate": IncidentStatus.ESCALATED,
    "acknowledge": IncidentStatus.ACKNOWLEDGED,
    "dismiss": IncidentStatus.DISMISSED,
}


class InvalidTransition(ValueError):
    """Raised when an analyst action is not allowed from the current state."""


def can_transition(current: IncidentStatus, target: IncidentStatus) -> bool:
    return target in ALLOWED_TRANSITIONS.get(current, set())


def apply_action(current: IncidentStatus, action: str) -> IncidentStatus:
    """Return the new status for an analyst action, or raise InvalidTransition."""
    key = (action or "").lower()
    if key not in ACTION_TO_STATUS:
        raise InvalidTransition(
            f"Unknown action {action!r}; expected one of {sorted(ACTION_TO_STATUS)}."
        )
    target = ACTION_TO_STATUS[key]
    if not can_transition(current, target):
        raise InvalidTransition(
            f"Cannot '{key}' an incident in state '{current.value}'."
        )
    return target
