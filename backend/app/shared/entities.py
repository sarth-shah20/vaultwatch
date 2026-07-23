"""
Shared entity model — the cross-cutting contract used by PS1, PS2, and the
quantum module. Agree on this schema as a team BEFORE building module-specific
logic; everything else should reference these types rather than defining
parallel/duplicate user models.

This is intentionally a stub (dataclasses, no DB/ORM specifics yet) so the team
can agree on shape first, then wire to Django/FastAPI/SQLAlchemy models once the
stack is confirmed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from uuid import uuid4


class EntityType(str, Enum):
    HUMAN = "human"
    SERVICE_ACCOUNT = "service_account"
    SCRIPT_OR_AUTOMATION = "script_or_automation"


class PrivilegeLevel(str, Enum):
    STANDARD = "standard"
    ELEVATED = "elevated"
    ADMIN = "admin"


@dataclass
class Entity:
    """Any actor in the system — human user, service account, or automation."""
    entity_id: str
    entity_type: EntityType
    display_name: str
    role: str | None = None                 # e.g. "DBA", "vendor", "batch-job"
    privilege_level: PrivilegeLevel = PrivilegeLevel.STANDARD
    department: str | None = None
    active: bool = True
    employment_end_date: datetime | None = None   # for offboarding hygiene checks
    hr_flag: str | None = None              # e.g. "termination_notice", "pip" (mocked signal)


@dataclass
class Reason:
    """A single structured justification for why a signal/alert fired.
    Every alert/incident should carry a list of these from creation — never
    just a bare score. See docs/ARCHITECTURE.md principle #2.
    """
    signal_name: str        # e.g. "unusual_access_time", "no_business_justification"
    domain: str              # "ps1_behavioral" | "ps2_telemetry" | "ps2_transaction" | "quantum"
    weight: float             # contribution to overall risk score, 0-1
    raw_value: str | None = None   # human-readable raw evidence, e.g. "accessed at 02:14 IST"


@dataclass
class RiskAssessment:
    """Output of any scoring component (PS1 risk scoring, PS2 fraud detection,
    correlation engine). Always includes reasons for explainability.
    """
    entity_id: str
    score: float                     # normalized 0-1 risk score
    reasons: list[Reason] = field(default_factory=list)
    # Versioned transport fields. Defaults preserve loading of existing snapshots.
    assessment_id: str = field(default_factory=lambda: str(uuid4()))
    schema_version: str = "1.0"
    domain: str = "unknown"
    event_time: datetime | None = None
    time_basis: str = "unknown"
    window_start: datetime | None = None
    window_end: datetime | None = None
    source: str = "unknown"
    model_version: str = "unknown"
    generated_at: datetime = field(default_factory=datetime.utcnow)


class AccessDecision(str, Enum):
    """Risk-based access control must resolve to one of these — a score alone
    is not a decision. See docs/ARCHITECTURE.md / CLAUDE.md principle #4."""
    ALLOW = "allow"
    STEP_UP_AUTH = "step_up_auth"
    THROTTLE = "throttle"
    REVOKE = "revoke"


class IncidentStatus(str, Enum):
    """Alert lifecycle states — see FEATURES.md PS2 item 7."""
    NEW = "new"
    ESCALATED = "escalated"
    ACKNOWLEDGED = "acknowledged"
    DISMISSED = "dismissed"


@dataclass
class UnifiedIncident:
    """The PS1 + PS2 bridge object — a single correlated, explained, risk-scored
    case that may combine a privileged-access signal with a transaction/telemetry
    signal. See docs/ARCHITECTURE.md 'The bridge' section.
    """
    incident_id: str
    entity_id: str
    combined_score: float
    contributing_assessments: list[RiskAssessment] = field(default_factory=list)
    status: IncidentStatus = IncidentStatus.NEW
    access_decision: AccessDecision | None = None
    # Correlation confidence: "high" when >=2 independent domains corroborate,
    # else "low" (a lone signal). Set by the correlation engine (Step 6).
    confidence: str | None = None
    contributing_domains: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.utcnow)
