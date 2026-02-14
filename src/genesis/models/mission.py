"""Mission, task, reviewer, evidence, and review-decision data models.

Every field maps directly to constitutional parameters or runtime policy.
No field is optional unless the constitution explicitly allows omission.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class RiskTier(str, enum.Enum):
    """Risk classification tiers (runtime_policy.json → risk_tiers)."""
    R0 = "R0"
    R1 = "R1"
    R2 = "R2"
    R3 = "R3"


class MissionClass(str, enum.Enum):
    """Mission classifications mapped to risk tiers in runtime policy."""
    DOCUMENTATION_UPDATE = "documentation_update"
    INTERNAL_OPERATIONS_CHANGE = "internal_operations_change"
    REGULATED_ANALYSIS = "regulated_analysis"
    CONSTITUTIONAL_CHANGE = "constitutional_change"
    LEAVE_ADJUDICATION = "leave_adjudication"


class DomainType(str, enum.Enum):
    """Domain classification for normative escalation."""
    OBJECTIVE = "objective"
    NORMATIVE = "normative"
    MIXED = "mixed"


class MissionState(str, enum.Enum):
    """Finite state machine states for a mission lifecycle."""
    DRAFT = "draft"
    SUBMITTED = "submitted"
    ASSIGNED = "assigned"
    IN_REVIEW = "in_review"
    REVIEW_COMPLETE = "review_complete"
    HUMAN_GATE_PENDING = "human_gate_pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


class TaskState(str, enum.Enum):
    """Task lifecycle states within a mission."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"


class ReviewDecisionVerdict(str, enum.Enum):
    """Reviewer verdict on a mission."""
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    ABSTAIN = "ABSTAIN"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Reviewer:
    """An assigned reviewer for a mission.

    Constitutional constraints enforced externally:
    - Worker cannot be a reviewer on the same mission.
    - model_family and method_type must be from valid canonical sets.
    - Region and organization used for diversity enforcement.
    """
    id: str
    model_family: str
    method_type: str
    region: str
    organization: str


@dataclass(frozen=True)
class ReviewDecision:
    """A single reviewer's decision on a mission."""
    reviewer_id: str
    decision: ReviewDecisionVerdict
    notes: str = ""
    timestamp_utc: Optional[datetime] = None


@dataclass(frozen=True)
class EvidenceRecord:
    """Tamper-evident evidence artifact attached to a mission.

    Both fields are mandatory per constitution:
    - artifact_hash: SHA-256 hash of the evidence artifact.
    - signature: Ed25519 signature over the artifact hash.
    """
    artifact_hash: str
    signature: str


@dataclass
class Task:
    """A discrete unit of work within a mission."""
    task_id: str
    description: str
    state: TaskState = TaskState.PENDING
    worker_id: Optional[str] = None
    evidence: list[EvidenceRecord] = field(default_factory=list)
    created_utc: Optional[datetime] = None
    completed_utc: Optional[datetime] = None


@dataclass
class Mission:
    """Top-level mission — the fundamental unit of accountable work.

    Every mission must have:
    - A mission class (determines risk tier via policy).
    - A domain type (determines normative escalation rules).
    - At least one evidence record before completion.
    - Review decisions meeting tier-specific approval thresholds.
    """
    mission_id: str
    mission_title: str
    mission_class: MissionClass
    risk_tier: RiskTier
    domain_type: DomainType
    state: MissionState = MissionState.DRAFT

    worker_id: Optional[str] = None
    reviewers: list[Reviewer] = field(default_factory=list)
    review_decisions: list[ReviewDecision] = field(default_factory=list)
    tasks: list[Task] = field(default_factory=list)
    evidence: list[EvidenceRecord] = field(default_factory=list)

    human_final_approval: bool = False

    # Skill requirements (optional — backward compatible)
    skill_requirements: list = field(default_factory=list)
    # Type: list[SkillRequirement] — untyped here to avoid circular import.
    # Validated in the service layer via SkillTaxonomy.

    created_utc: Optional[datetime] = None
    completed_utc: Optional[datetime] = None
