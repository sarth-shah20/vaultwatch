"""Tests for the alert lifecycle state machine."""
from __future__ import annotations

import pytest

from backend.app.core.lifecycle import InvalidTransition, apply_action, can_transition
from backend.app.shared.entities import IncidentStatus


def test_valid_transitions() -> None:
    assert apply_action(IncidentStatus.NEW, "escalate") is IncidentStatus.ESCALATED
    assert apply_action(IncidentStatus.NEW, "dismiss") is IncidentStatus.DISMISSED
    assert apply_action(IncidentStatus.ESCALATED, "acknowledge") is IncidentStatus.ACKNOWLEDGED
    assert apply_action(IncidentStatus.ACKNOWLEDGED, "dismiss") is IncidentStatus.DISMISSED


def test_dismissed_is_terminal() -> None:
    assert can_transition(IncidentStatus.DISMISSED, IncidentStatus.ESCALATED) is False
    with pytest.raises(InvalidTransition):
        apply_action(IncidentStatus.DISMISSED, "escalate")


def test_unknown_action_rejected() -> None:
    with pytest.raises(InvalidTransition):
        apply_action(IncidentStatus.NEW, "frobnicate")
