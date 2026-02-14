"""Protected leave data models — leave requests, adjudications, records.

Protected leave freezes trust decay during verified life events.
The mechanism uses Genesis's own trust infrastructure: a quorum of
domain-qualified professionals adjudicates leave requests. No external
bureaucracy. The record is auditable, hashed, and blockchain-anchored.

Principles:
- Leave is a right for verified life events, not a loophole.
- Quorum adjudication (minimum 3) prevents single-entity gaming.
- Adjudicators must have domain trust in relevant professional fields.
- Trust is frozen exactly — no gain, no loss, decay clock stops.
- Return is possible but not required.

Protected categories:
- Illness, bereavement, disability, mental health, caregiving,
  pregnancy, child care, and death (memorialisation).

Death/memorialisation:
- Petitioned by a third party (relative, friend, colleague) — not self.
- Quorum-adjudicated with evidence, same as all other categories.
- Account permanently memorialised — trust frozen, never reactivated.
- The person's record stands honestly forever.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


class LeaveCategory(str, enum.Enum):
    """Categories of protected life events.

    Each category maps to required adjudicator domains — the professional
    fields that qualify someone to assess a leave request of this type.
    """
    ILLNESS = "illness"
    BEREAVEMENT = "bereavement"
    DISABILITY = "disability"
    MENTAL_HEALTH = "mental_health"
    CAREGIVER = "caregiver"
    PREGNANCY = "pregnancy"
    CHILD_CARE = "child_care"
    DEATH = "death"


# Default mapping from category to required adjudicator domains.
# Policy config can override this.
CATEGORY_REQUIRED_DOMAINS: dict[str, list[str]] = {
    "illness": ["healthcare"],
    "bereavement": ["social_services", "mental_health"],
    "disability": ["healthcare", "social_services"],
    "mental_health": ["mental_health", "healthcare"],
    "caregiver": ["social_services"],
    "pregnancy": ["healthcare"],
    "child_care": ["social_services"],
    "death": ["healthcare", "social_services"],
}


class LeaveState(str, enum.Enum):
    """Lifecycle states for a leave request.

    PENDING → APPROVED/DENIED (after quorum)
    APPROVED → ACTIVE (trust frozen)
    ACTIVE → RETURNED (actor comes back) or MEMORIALISED (death)

    Memorialisation:
    - Petitioned by a third party with evidence of death.
    - Quorum-adjudicated.
    - Account sealed permanently — trust frozen, never reactivated.
    """
    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    ACTIVE = "active"
    RETURNED = "returned"
    MEMORIALISED = "memorialised"


class AdjudicationVerdict(str, enum.Enum):
    """Individual adjudicator's verdict on a leave request."""
    APPROVE = "approve"
    DENY = "deny"
    ABSTAIN = "abstain"


@dataclass(frozen=True)
class LeaveAdjudication:
    """A single adjudicator's verdict on a leave request.

    Adjudicators must have earned domain trust in the relevant
    professional field (healthcare, mental_health, social_services).
    Their trust score at the time of decision is permanently recorded
    for audit transparency.
    """
    adjudicator_id: str
    verdict: AdjudicationVerdict
    domain_qualified: str        # The domain they qualified under
    trust_score_at_decision: float
    notes: str = ""
    timestamp_utc: Optional[datetime] = None


@dataclass
class LeaveRecord:
    """A protected leave record for an actor.

    Trust freeze semantics:
    - trust_score_at_freeze: exact score preserved from freeze moment
    - last_active_utc_at_freeze: the original last_active timestamp
    - domain_scores_at_freeze: snapshot of all domain scores

    On return, trust score is preserved and last_active_utc is set to
    the return timestamp (so decay resumes from return, not from
    original last-activity).

    Duration limits:
    - granted_duration_days: maximum days of leave (None = unlimited)
    - expires_utc: computed at approval time from grant + duration
    - Extensions require a new adjudication (same quorum process)
    """
    leave_id: str
    actor_id: str
    category: LeaveCategory
    state: LeaveState = LeaveState.PENDING
    reason_summary: str = ""     # Brief, private, not public
    petitioner_id: Optional[str] = None  # Third-party petitioner (death only)

    # Adjudication
    adjudications: list[LeaveAdjudication] = field(default_factory=list)

    # Freeze snapshot (populated on approval)
    trust_score_at_freeze: Optional[float] = None
    last_active_utc_at_freeze: Optional[datetime] = None
    domain_scores_at_freeze: dict = field(default_factory=dict)
    # Type: dict[str, DomainTrustScore] — untyped to avoid circular import.
    # Serialised on persist.

    # Pre-leave actor status (to restore on return — prevents status escalation)
    pre_leave_status: Optional[str] = None

    # Duration limits
    granted_duration_days: Optional[int] = None
    expires_utc: Optional[datetime] = None

    # Timestamps
    requested_utc: Optional[datetime] = None
    approved_utc: Optional[datetime] = None
    denied_utc: Optional[datetime] = None
    returned_utc: Optional[datetime] = None
    memorialised_utc: Optional[datetime] = None

    def approve_count(self) -> int:
        """Count adjudicators who voted APPROVE."""
        return sum(1 for a in self.adjudications
                   if a.verdict == AdjudicationVerdict.APPROVE)

    def deny_count(self) -> int:
        """Count adjudicators who voted DENY."""
        return sum(1 for a in self.adjudications
                   if a.verdict == AdjudicationVerdict.DENY)

    def abstain_count(self) -> int:
        """Count adjudicators who voted ABSTAIN."""
        return sum(1 for a in self.adjudications
                   if a.verdict == AdjudicationVerdict.ABSTAIN)

    def has_quorum(self, min_quorum: int) -> bool:
        """Check if enough adjudicators have voted (approve or deny).

        Abstentions do not count toward quorum.
        """
        non_abstain = self.approve_count() + self.deny_count()
        return non_abstain >= min_quorum
