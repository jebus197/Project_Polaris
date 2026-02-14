"""Leave adjudication engine — validates adjudicator eligibility,
computes quorum, and determines leave approval.

Pure computation: no side effects. The service layer handles
event recording, persistence, and state mutations.

Constitutional invariants:
- Only humans can adjudicate leave (machines lack authority).
- Self-adjudication is structurally blocked.
- Adjudicators must have earned domain trust in relevant
  professional fields (healthcare, mental_health, social_services).
- Quorum of 3+ prevents single-entity gaming.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

from genesis.models.leave import (
    AdjudicationVerdict,
    LeaveAdjudication,
    LeaveCategory,
    LeaveRecord,
    LeaveState,
)
from genesis.models.trust import ActorKind, TrustRecord
from genesis.models.domain_trust import DomainTrustScore
from genesis.review.roster import ActorStatus, RosterEntry
from genesis.policy.resolver import PolicyResolver


@dataclass(frozen=True)
class AdjudicatorEligibility:
    """Result of checking adjudicator eligibility."""
    eligible: bool
    errors: list[str] = field(default_factory=list)
    qualifying_domain: str = ""


@dataclass(frozen=True)
class QuorumResult:
    """Result of evaluating whether quorum is reached and leave outcome."""
    quorum_reached: bool
    approved: bool
    approve_count: int
    deny_count: int
    abstain_count: int
    total_adjudicators: int
    required_quorum: int
    required_approvals: int


class LeaveAdjudicationEngine:
    """Validates eligibility and computes leave adjudication outcomes.

    Pure computation — no side effects. Receives state, returns results.
    The service layer uses these results to decide what mutations to make.
    """

    def __init__(self, resolver: PolicyResolver) -> None:
        self._resolver = resolver

    def check_adjudicator_eligibility(
        self,
        adjudicator_entry: RosterEntry,
        adjudicator_trust: TrustRecord,
        leave_category: LeaveCategory,
        applicant_id: str,
    ) -> AdjudicatorEligibility:
        """Check if an actor is eligible to adjudicate a leave request.

        Requirements:
        1. Must not be the applicant (self-adjudication blocked)
        2. Must be HUMAN (constitutional authority)
        3. Must be ACTIVE or PROBATION (not quarantined/on_leave/decommissioned)
        4. Must have global trust >= min_adjudicator_trust
        5. Must have domain trust >= min_domain_trust in a required domain
           for the leave category
        """
        config = self._resolver.leave_adjudication_config()
        errors: list[str] = []

        # 1. Self-adjudication blocked
        if adjudicator_entry.actor_id == applicant_id:
            errors.append("Cannot adjudicate own leave request")
            return AdjudicatorEligibility(eligible=False, errors=errors)

        # 2. Must be human
        if adjudicator_entry.actor_kind != ActorKind.HUMAN:
            errors.append("Only humans can adjudicate leave requests")
            return AdjudicatorEligibility(eligible=False, errors=errors)

        # 3. Must be active
        if not adjudicator_entry.is_available():
            errors.append(
                f"Adjudicator status is {adjudicator_entry.status.value}; "
                f"must be active or probation"
            )
            return AdjudicatorEligibility(eligible=False, errors=errors)

        # 4. Global trust threshold
        min_trust = config.get("min_adjudicator_trust", 0.40)
        if adjudicator_trust.score < min_trust:
            errors.append(
                f"Global trust {adjudicator_trust.score:.3f} "
                f"< required {min_trust:.3f}"
            )
            return AdjudicatorEligibility(eligible=False, errors=errors)

        # 5. Domain trust in required professional field
        min_domain_trust = config.get("min_domain_trust", 0.30)
        cat_config = self._resolver.leave_category_config(
            leave_category.value,
        )
        required_domains = cat_config.get(
            "required_adjudicator_domains", ["healthcare"],
        )

        qualifying_domain = ""
        for domain in required_domains:
            ds = adjudicator_trust.domain_scores.get(domain)
            if ds is not None and isinstance(ds, DomainTrustScore):
                if ds.score >= min_domain_trust:
                    qualifying_domain = domain
                    break

        if not qualifying_domain:
            errors.append(
                f"No qualifying domain trust >= {min_domain_trust:.3f} "
                f"in required domains: {required_domains}"
            )
            return AdjudicatorEligibility(eligible=False, errors=errors)

        return AdjudicatorEligibility(
            eligible=True,
            errors=[],
            qualifying_domain=qualifying_domain,
        )

    def evaluate_quorum(self, record: LeaveRecord) -> QuorumResult:
        """Evaluate whether a leave request has reached quorum and the outcome.

        Quorum is reached when the number of non-abstain votes >= min_quorum.
        Leave is approved if approve_count >= min_approve_to_grant.
        """
        config = self._resolver.leave_adjudication_config()
        min_quorum = config.get("min_quorum", 3)
        min_approvals = config.get("min_approve_to_grant", 2)

        approve = record.approve_count()
        deny = record.deny_count()
        abstain = record.abstain_count()
        total = len(record.adjudications)
        non_abstain = approve + deny

        quorum_reached = non_abstain >= min_quorum
        approved = quorum_reached and approve >= min_approvals

        return QuorumResult(
            quorum_reached=quorum_reached,
            approved=approved,
            approve_count=approve,
            deny_count=deny,
            abstain_count=abstain,
            total_adjudicators=total,
            required_quorum=min_quorum,
            required_approvals=min_approvals,
        )

    def check_adjudicator_diversity(
        self,
        adjudicator_entries: dict[str, RosterEntry],
    ) -> list[str]:
        """Check that approving adjudicators satisfy diversity constraints.

        Returns list of violations (empty = passes).

        Configured constraints:
        - min_organizations: minimum distinct organisations among adjudicators
        - min_regions: minimum distinct regions among adjudicators
        """
        config = self._resolver.leave_adjudication_config()
        diversity = config.get("adjudicator_diversity", {})
        min_orgs = diversity.get("min_organizations", 2)
        min_regions = diversity.get("min_regions", 2)

        violations: list[str] = []
        if not adjudicator_entries:
            return violations

        orgs = {e.organization for e in adjudicator_entries.values()}
        regions = {e.region for e in adjudicator_entries.values()}

        if len(orgs) < min_orgs:
            violations.append(
                f"Adjudicator diversity: {len(orgs)} distinct organisation(s), "
                f"minimum required is {min_orgs}"
            )
        if len(regions) < min_regions:
            violations.append(
                f"Adjudicator diversity: {len(regions)} distinct region(s), "
                f"minimum required is {min_regions}"
            )

        return violations

    def check_anti_gaming(
        self,
        actor_id: str,
        existing_leaves: list[LeaveRecord],
        now: Optional[datetime] = None,
    ) -> list[str]:
        """Check anti-gaming constraints. Returns list of violations.

        Checks:
        1. Cooldown between leaves (default 30 days)
        2. Max leaves per year (default 4)
        """
        now = now or datetime.now(timezone.utc)
        config = self._resolver.leave_anti_gaming_config()
        violations: list[str] = []

        # Cooldown between leaves
        cooldown_days = config.get("cooldown_days_between_leaves", 30)
        for leave in existing_leaves:
            if leave.state in (
                LeaveState.RETURNED, LeaveState.MEMORIALISED,
                LeaveState.ACTIVE, LeaveState.APPROVED,
            ):
                end_time = leave.returned_utc or leave.approved_utc
                if end_time:
                    days_since = (now - end_time).total_seconds() / 86400.0
                    if days_since < cooldown_days:
                        violations.append(
                            f"Cooldown: {days_since:.0f} days since last "
                            f"leave, minimum is {cooldown_days}"
                        )

        # Max leaves per year
        max_per_year = config.get("max_leaves_per_year", 4)
        one_year_ago = now - timedelta(days=365)
        recent_leaves = [
            leave for leave in existing_leaves
            if leave.requested_utc and leave.requested_utc > one_year_ago
            and leave.state != LeaveState.DENIED
        ]
        if len(recent_leaves) >= max_per_year:
            violations.append(
                f"Max leaves per year: {len(recent_leaves)} "
                f"of {max_per_year} used"
            )

        return violations

    def check_leave_expiry(
        self,
        record: LeaveRecord,
        now: Optional[datetime] = None,
    ) -> bool:
        """Check if an active leave has expired.

        Returns True if the leave has expired (i.e., now > expires_utc).
        Categories with max_duration_days get an expires_utc computed
        at approval time. Unlimited categories return False.
        """
        if record.state != LeaveState.ACTIVE:
            return False
        if record.expires_utc is None:
            return False
        now = now or datetime.now(timezone.utc)
        return now > record.expires_utc

    def compute_expires_utc(
        self,
        category: LeaveCategory,
        approved_utc: datetime,
    ) -> Optional[datetime]:
        """Compute expiry timestamp based on category duration limits.

        Returns None for unlimited categories.
        """
        duration_config = self._resolver.leave_duration_config()
        overrides = duration_config.get("category_overrides", {})
        default_max = duration_config.get("default_max_days")

        max_days = overrides.get(category.value, default_max)
        if max_days is None:
            return None

        return approved_utc + timedelta(days=max_days)
