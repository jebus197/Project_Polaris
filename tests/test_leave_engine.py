"""Unit tests for the leave adjudication engine.

Tests eligibility checks, quorum evaluation, anti-gaming, expiry,
and duration computation. Pure computation — no side effects.
"""

import pytest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from genesis.leave.engine import (
    AdjudicatorEligibility,
    LeaveAdjudicationEngine,
    QuorumResult,
)
from genesis.models.domain_trust import DomainTrustScore
from genesis.models.leave import (
    AdjudicationVerdict,
    LeaveAdjudication,
    LeaveCategory,
    LeaveRecord,
    LeaveState,
)
from genesis.models.trust import ActorKind, TrustRecord
from genesis.policy.resolver import PolicyResolver
from genesis.review.roster import ActorStatus, RosterEntry

CONFIG_DIR = Path(__file__).parent.parent / "config"


def _make_resolver() -> PolicyResolver:
    """Create a PolicyResolver from the real config directory."""
    return PolicyResolver.from_config_dir(CONFIG_DIR)


def _make_roster_entry(
    actor_id: str = "ADJ-001",
    kind: ActorKind = ActorKind.HUMAN,
    status: ActorStatus = ActorStatus.ACTIVE,
    trust_score: float = 0.60,
    region: str = "EU",
    organization: str = "MedOrg",
) -> RosterEntry:
    return RosterEntry(
        actor_id=actor_id,
        actor_kind=kind,
        trust_score=trust_score,
        region=region,
        organization=organization,
        model_family="human_reviewer",
        method_type="human_reviewer",
        status=status,
    )


def _make_trust_record(
    actor_id: str = "ADJ-001",
    kind: ActorKind = ActorKind.HUMAN,
    score: float = 0.60,
    domain_scores: dict | None = None,
) -> TrustRecord:
    ds = domain_scores or {}
    record = TrustRecord(actor_id=actor_id, actor_kind=kind, score=score)
    record.domain_scores = ds
    return record


def _make_domain_trust(domain: str, score: float) -> DomainTrustScore:
    return DomainTrustScore(domain=domain, score=score)


# ===================================================================
# Adjudicator eligibility checks
# ===================================================================

class TestAdjudicatorEligibility:
    def test_eligible_adjudicator(self) -> None:
        engine = LeaveAdjudicationEngine(_make_resolver())
        entry = _make_roster_entry()
        trust = _make_trust_record(
            domain_scores={"healthcare": _make_domain_trust("healthcare", 0.50)},
        )
        result = engine.check_adjudicator_eligibility(
            entry, trust, LeaveCategory.ILLNESS, "APPLICANT-001",
        )
        assert result.eligible is True
        assert result.qualifying_domain == "healthcare"
        assert result.errors == []

    def test_self_adjudication_blocked(self) -> None:
        engine = LeaveAdjudicationEngine(_make_resolver())
        entry = _make_roster_entry(actor_id="ACTOR-001")
        trust = _make_trust_record(
            actor_id="ACTOR-001",
            domain_scores={"healthcare": _make_domain_trust("healthcare", 0.50)},
        )
        result = engine.check_adjudicator_eligibility(
            entry, trust, LeaveCategory.ILLNESS, "ACTOR-001",
        )
        assert result.eligible is False
        assert "Cannot adjudicate own leave request" in result.errors[0]

    def test_machine_cannot_adjudicate(self) -> None:
        engine = LeaveAdjudicationEngine(_make_resolver())
        entry = _make_roster_entry(kind=ActorKind.MACHINE)
        trust = _make_trust_record(
            kind=ActorKind.MACHINE,
            domain_scores={"healthcare": _make_domain_trust("healthcare", 0.50)},
        )
        result = engine.check_adjudicator_eligibility(
            entry, trust, LeaveCategory.ILLNESS, "APPLICANT-001",
        )
        assert result.eligible is False
        assert "Only humans" in result.errors[0]

    def test_quarantined_actor_ineligible(self) -> None:
        engine = LeaveAdjudicationEngine(_make_resolver())
        entry = _make_roster_entry(status=ActorStatus.QUARANTINED)
        trust = _make_trust_record(
            domain_scores={"healthcare": _make_domain_trust("healthcare", 0.50)},
        )
        result = engine.check_adjudicator_eligibility(
            entry, trust, LeaveCategory.ILLNESS, "APPLICANT-001",
        )
        assert result.eligible is False
        assert "must be active or probation" in result.errors[0]

    def test_decommissioned_actor_ineligible(self) -> None:
        engine = LeaveAdjudicationEngine(_make_resolver())
        entry = _make_roster_entry(status=ActorStatus.DECOMMISSIONED)
        trust = _make_trust_record(
            domain_scores={"healthcare": _make_domain_trust("healthcare", 0.50)},
        )
        result = engine.check_adjudicator_eligibility(
            entry, trust, LeaveCategory.ILLNESS, "APPLICANT-001",
        )
        assert result.eligible is False

    def test_on_leave_actor_ineligible(self) -> None:
        engine = LeaveAdjudicationEngine(_make_resolver())
        entry = _make_roster_entry(status=ActorStatus.ON_LEAVE)
        trust = _make_trust_record(
            domain_scores={"healthcare": _make_domain_trust("healthcare", 0.50)},
        )
        result = engine.check_adjudicator_eligibility(
            entry, trust, LeaveCategory.ILLNESS, "APPLICANT-001",
        )
        assert result.eligible is False

    def test_probation_actor_eligible(self) -> None:
        engine = LeaveAdjudicationEngine(_make_resolver())
        entry = _make_roster_entry(status=ActorStatus.PROBATION)
        trust = _make_trust_record(
            domain_scores={"healthcare": _make_domain_trust("healthcare", 0.50)},
        )
        result = engine.check_adjudicator_eligibility(
            entry, trust, LeaveCategory.ILLNESS, "APPLICANT-001",
        )
        assert result.eligible is True

    def test_global_trust_too_low(self) -> None:
        engine = LeaveAdjudicationEngine(_make_resolver())
        entry = _make_roster_entry(trust_score=0.30)
        trust = _make_trust_record(
            score=0.30,
            domain_scores={"healthcare": _make_domain_trust("healthcare", 0.50)},
        )
        result = engine.check_adjudicator_eligibility(
            entry, trust, LeaveCategory.ILLNESS, "APPLICANT-001",
        )
        assert result.eligible is False
        assert "Global trust" in result.errors[0]

    def test_domain_trust_too_low(self) -> None:
        engine = LeaveAdjudicationEngine(_make_resolver())
        entry = _make_roster_entry()
        trust = _make_trust_record(
            domain_scores={"healthcare": _make_domain_trust("healthcare", 0.10)},
        )
        result = engine.check_adjudicator_eligibility(
            entry, trust, LeaveCategory.ILLNESS, "APPLICANT-001",
        )
        assert result.eligible is False
        assert "No qualifying domain trust" in result.errors[0]

    def test_no_domain_trust_at_all(self) -> None:
        engine = LeaveAdjudicationEngine(_make_resolver())
        entry = _make_roster_entry()
        trust = _make_trust_record(domain_scores={})
        result = engine.check_adjudicator_eligibility(
            entry, trust, LeaveCategory.ILLNESS, "APPLICANT-001",
        )
        assert result.eligible is False

    def test_wrong_domain(self) -> None:
        """Has domain trust but not in the required domain."""
        engine = LeaveAdjudicationEngine(_make_resolver())
        entry = _make_roster_entry()
        trust = _make_trust_record(
            domain_scores={"social_services": _make_domain_trust("social_services", 0.80)},
        )
        # illness requires healthcare, not social_services
        result = engine.check_adjudicator_eligibility(
            entry, trust, LeaveCategory.ILLNESS, "APPLICANT-001",
        )
        assert result.eligible is False

    def test_bereavement_social_services_qualifies(self) -> None:
        engine = LeaveAdjudicationEngine(_make_resolver())
        entry = _make_roster_entry()
        trust = _make_trust_record(
            domain_scores={"social_services": _make_domain_trust("social_services", 0.50)},
        )
        result = engine.check_adjudicator_eligibility(
            entry, trust, LeaveCategory.BEREAVEMENT, "APPLICANT-001",
        )
        assert result.eligible is True
        assert result.qualifying_domain == "social_services"

    def test_bereavement_mental_health_qualifies(self) -> None:
        engine = LeaveAdjudicationEngine(_make_resolver())
        entry = _make_roster_entry()
        trust = _make_trust_record(
            domain_scores={"mental_health": _make_domain_trust("mental_health", 0.50)},
        )
        result = engine.check_adjudicator_eligibility(
            entry, trust, LeaveCategory.BEREAVEMENT, "APPLICANT-001",
        )
        assert result.eligible is True
        assert result.qualifying_domain == "mental_health"

    def test_pregnancy_requires_healthcare(self) -> None:
        engine = LeaveAdjudicationEngine(_make_resolver())
        entry = _make_roster_entry()
        trust = _make_trust_record(
            domain_scores={"healthcare": _make_domain_trust("healthcare", 0.50)},
        )
        result = engine.check_adjudicator_eligibility(
            entry, trust, LeaveCategory.PREGNANCY, "APPLICANT-001",
        )
        assert result.eligible is True
        assert result.qualifying_domain == "healthcare"

    def test_child_care_requires_social_services(self) -> None:
        engine = LeaveAdjudicationEngine(_make_resolver())
        entry = _make_roster_entry()
        trust = _make_trust_record(
            domain_scores={"social_services": _make_domain_trust("social_services", 0.50)},
        )
        result = engine.check_adjudicator_eligibility(
            entry, trust, LeaveCategory.CHILD_CARE, "APPLICANT-001",
        )
        assert result.eligible is True
        assert result.qualifying_domain == "social_services"

    def test_global_trust_at_boundary(self) -> None:
        """Trust at exactly min_adjudicator_trust should pass."""
        engine = LeaveAdjudicationEngine(_make_resolver())
        entry = _make_roster_entry(trust_score=0.40)
        trust = _make_trust_record(
            score=0.40,
            domain_scores={"healthcare": _make_domain_trust("healthcare", 0.50)},
        )
        result = engine.check_adjudicator_eligibility(
            entry, trust, LeaveCategory.ILLNESS, "APPLICANT-001",
        )
        assert result.eligible is True

    def test_domain_trust_at_boundary(self) -> None:
        """Domain trust at exactly min_domain_trust should pass."""
        engine = LeaveAdjudicationEngine(_make_resolver())
        entry = _make_roster_entry()
        trust = _make_trust_record(
            domain_scores={"healthcare": _make_domain_trust("healthcare", 0.30)},
        )
        result = engine.check_adjudicator_eligibility(
            entry, trust, LeaveCategory.ILLNESS, "APPLICANT-001",
        )
        assert result.eligible is True


# ===================================================================
# Quorum evaluation
# ===================================================================

class TestEvaluateQuorum:
    def _make_record_with_votes(self, approves=0, denies=0, abstains=0) -> LeaveRecord:
        adjs = []
        for i in range(approves):
            adjs.append(LeaveAdjudication(
                f"A{i}", AdjudicationVerdict.APPROVE, "healthcare", 0.5,
            ))
        for i in range(denies):
            adjs.append(LeaveAdjudication(
                f"D{i}", AdjudicationVerdict.DENY, "healthcare", 0.5,
            ))
        for i in range(abstains):
            adjs.append(LeaveAdjudication(
                f"AB{i}", AdjudicationVerdict.ABSTAIN, "healthcare", 0.5,
            ))
        record = LeaveRecord(
            leave_id="L1", actor_id="ACTOR-001", category=LeaveCategory.ILLNESS,
        )
        record.adjudications = adjs
        return record

    def test_no_votes_no_quorum(self) -> None:
        engine = LeaveAdjudicationEngine(_make_resolver())
        result = engine.evaluate_quorum(self._make_record_with_votes())
        assert result.quorum_reached is False
        assert result.approved is False

    def test_three_approves_quorum_and_approved(self) -> None:
        engine = LeaveAdjudicationEngine(_make_resolver())
        result = engine.evaluate_quorum(self._make_record_with_votes(approves=3))
        assert result.quorum_reached is True
        assert result.approved is True
        assert result.approve_count == 3

    def test_two_approve_one_deny_quorum_and_approved(self) -> None:
        engine = LeaveAdjudicationEngine(_make_resolver())
        result = engine.evaluate_quorum(self._make_record_with_votes(approves=2, denies=1))
        assert result.quorum_reached is True
        assert result.approved is True

    def test_one_approve_two_deny_quorum_but_denied(self) -> None:
        engine = LeaveAdjudicationEngine(_make_resolver())
        result = engine.evaluate_quorum(self._make_record_with_votes(approves=1, denies=2))
        assert result.quorum_reached is True
        assert result.approved is False

    def test_three_denies_quorum_but_denied(self) -> None:
        engine = LeaveAdjudicationEngine(_make_resolver())
        result = engine.evaluate_quorum(self._make_record_with_votes(denies=3))
        assert result.quorum_reached is True
        assert result.approved is False

    def test_abstentions_dont_count_toward_quorum(self) -> None:
        engine = LeaveAdjudicationEngine(_make_resolver())
        result = engine.evaluate_quorum(
            self._make_record_with_votes(approves=2, abstains=3),
        )
        assert result.quorum_reached is False
        assert result.approved is False

    def test_two_approve_two_deny_no_quorum(self) -> None:
        """4 non-abstain votes >= quorum of 3, but only 2 approvals < needed 2? No: 2 >= 2."""
        engine = LeaveAdjudicationEngine(_make_resolver())
        result = engine.evaluate_quorum(
            self._make_record_with_votes(approves=2, denies=2),
        )
        assert result.quorum_reached is True
        assert result.approved is True  # 2 approvals >= 2 required

    def test_quorum_result_fields(self) -> None:
        engine = LeaveAdjudicationEngine(_make_resolver())
        result = engine.evaluate_quorum(
            self._make_record_with_votes(approves=2, denies=1, abstains=1),
        )
        assert result.approve_count == 2
        assert result.deny_count == 1
        assert result.abstain_count == 1
        assert result.total_adjudicators == 4
        assert result.required_quorum == 3
        assert result.required_approvals == 2


# ===================================================================
# Anti-gaming checks
# ===================================================================

class TestAntiGaming:
    def test_no_violations_with_empty_history(self) -> None:
        engine = LeaveAdjudicationEngine(_make_resolver())
        violations = engine.check_anti_gaming("ACTOR-001", [])
        assert violations == []

    def test_cooldown_violation(self) -> None:
        engine = LeaveAdjudicationEngine(_make_resolver())
        now = datetime.now(timezone.utc)
        recent_leave = LeaveRecord(
            leave_id="L1", actor_id="ACTOR-001", category=LeaveCategory.ILLNESS,
            state=LeaveState.RETURNED,
            approved_utc=now - timedelta(days=10),
            returned_utc=now - timedelta(days=5),
        )
        violations = engine.check_anti_gaming("ACTOR-001", [recent_leave], now=now)
        assert len(violations) == 1
        assert "Cooldown" in violations[0]

    def test_no_cooldown_after_30_days(self) -> None:
        engine = LeaveAdjudicationEngine(_make_resolver())
        now = datetime.now(timezone.utc)
        old_leave = LeaveRecord(
            leave_id="L1", actor_id="ACTOR-001", category=LeaveCategory.ILLNESS,
            state=LeaveState.RETURNED,
            approved_utc=now - timedelta(days=60),
            returned_utc=now - timedelta(days=35),
        )
        violations = engine.check_anti_gaming("ACTOR-001", [old_leave], now=now)
        assert violations == []

    def test_max_per_year_violation(self) -> None:
        engine = LeaveAdjudicationEngine(_make_resolver())
        now = datetime.now(timezone.utc)
        leaves = []
        for i in range(4):
            leaves.append(LeaveRecord(
                leave_id=f"L{i}", actor_id="ACTOR-001", category=LeaveCategory.ILLNESS,
                state=LeaveState.RETURNED,
                requested_utc=now - timedelta(days=300 - i * 50),
                approved_utc=now - timedelta(days=300 - i * 50),
                returned_utc=now - timedelta(days=250 - i * 50),
            ))
        violations = engine.check_anti_gaming("ACTOR-001", leaves, now=now)
        assert any("Max leaves per year" in v for v in violations)

    def test_denied_leaves_dont_count_toward_max(self) -> None:
        engine = LeaveAdjudicationEngine(_make_resolver())
        now = datetime.now(timezone.utc)
        leaves = []
        for i in range(4):
            leaves.append(LeaveRecord(
                leave_id=f"L{i}", actor_id="ACTOR-001", category=LeaveCategory.ILLNESS,
                state=LeaveState.DENIED,
                requested_utc=now - timedelta(days=300 - i * 50),
            ))
        violations = engine.check_anti_gaming("ACTOR-001", leaves, now=now)
        # Denied leaves don't count toward max
        assert not any("Max leaves per year" in v for v in violations)

    def test_cooldown_checks_returned_utc(self) -> None:
        """Cooldown is based on returned_utc (or approved_utc), not requested_utc."""
        engine = LeaveAdjudicationEngine(_make_resolver())
        now = datetime.now(timezone.utc)
        leave = LeaveRecord(
            leave_id="L1", actor_id="ACTOR-001", category=LeaveCategory.ILLNESS,
            state=LeaveState.RETURNED,
            requested_utc=now - timedelta(days=100),
            approved_utc=now - timedelta(days=90),
            returned_utc=now - timedelta(days=10),  # Only 10 days ago
        )
        violations = engine.check_anti_gaming("ACTOR-001", [leave], now=now)
        assert len(violations) >= 1
        assert "Cooldown" in violations[0]


# ===================================================================
# Leave expiry checks
# ===================================================================

class TestLeaveExpiry:
    def test_active_leave_not_expired(self) -> None:
        engine = LeaveAdjudicationEngine(_make_resolver())
        now = datetime.now(timezone.utc)
        record = LeaveRecord(
            leave_id="L1", actor_id="ACTOR-001", category=LeaveCategory.PREGNANCY,
            state=LeaveState.ACTIVE,
            expires_utc=now + timedelta(days=100),
        )
        assert engine.check_leave_expiry(record, now=now) is False

    def test_active_leave_expired(self) -> None:
        engine = LeaveAdjudicationEngine(_make_resolver())
        now = datetime.now(timezone.utc)
        record = LeaveRecord(
            leave_id="L1", actor_id="ACTOR-001", category=LeaveCategory.PREGNANCY,
            state=LeaveState.ACTIVE,
            expires_utc=now - timedelta(days=1),
        )
        assert engine.check_leave_expiry(record, now=now) is True

    def test_no_expiry_never_expires(self) -> None:
        engine = LeaveAdjudicationEngine(_make_resolver())
        record = LeaveRecord(
            leave_id="L1", actor_id="ACTOR-001", category=LeaveCategory.ILLNESS,
            state=LeaveState.ACTIVE,
            expires_utc=None,
        )
        assert engine.check_leave_expiry(record) is False

    def test_non_active_state_never_expires(self) -> None:
        engine = LeaveAdjudicationEngine(_make_resolver())
        now = datetime.now(timezone.utc)
        record = LeaveRecord(
            leave_id="L1", actor_id="ACTOR-001", category=LeaveCategory.PREGNANCY,
            state=LeaveState.PENDING,
            expires_utc=now - timedelta(days=1),
        )
        assert engine.check_leave_expiry(record, now=now) is False

    def test_returned_leave_not_checked(self) -> None:
        engine = LeaveAdjudicationEngine(_make_resolver())
        now = datetime.now(timezone.utc)
        record = LeaveRecord(
            leave_id="L1", actor_id="ACTOR-001", category=LeaveCategory.PREGNANCY,
            state=LeaveState.RETURNED,
            expires_utc=now - timedelta(days=1),
        )
        assert engine.check_leave_expiry(record, now=now) is False


# ===================================================================
# Duration computation
# ===================================================================

class TestComputeExpiresUtc:
    def test_pregnancy_gets_365_days(self) -> None:
        engine = LeaveAdjudicationEngine(_make_resolver())
        now = datetime.now(timezone.utc)
        expires = engine.compute_expires_utc(LeaveCategory.PREGNANCY, now)
        assert expires is not None
        expected = now + timedelta(days=365)
        assert abs((expires - expected).total_seconds()) < 1

    def test_child_care_gets_365_days(self) -> None:
        engine = LeaveAdjudicationEngine(_make_resolver())
        now = datetime.now(timezone.utc)
        expires = engine.compute_expires_utc(LeaveCategory.CHILD_CARE, now)
        assert expires is not None
        expected = now + timedelta(days=365)
        assert abs((expires - expected).total_seconds()) < 1

    def test_illness_no_duration_limit(self) -> None:
        engine = LeaveAdjudicationEngine(_make_resolver())
        now = datetime.now(timezone.utc)
        expires = engine.compute_expires_utc(LeaveCategory.ILLNESS, now)
        assert expires is None

    def test_bereavement_no_duration_limit(self) -> None:
        engine = LeaveAdjudicationEngine(_make_resolver())
        now = datetime.now(timezone.utc)
        expires = engine.compute_expires_utc(LeaveCategory.BEREAVEMENT, now)
        assert expires is None

    def test_disability_no_duration_limit(self) -> None:
        engine = LeaveAdjudicationEngine(_make_resolver())
        now = datetime.now(timezone.utc)
        expires = engine.compute_expires_utc(LeaveCategory.DISABILITY, now)
        assert expires is None

    def test_mental_health_no_duration_limit(self) -> None:
        engine = LeaveAdjudicationEngine(_make_resolver())
        now = datetime.now(timezone.utc)
        expires = engine.compute_expires_utc(LeaveCategory.MENTAL_HEALTH, now)
        assert expires is None

    def test_caregiver_no_duration_limit(self) -> None:
        engine = LeaveAdjudicationEngine(_make_resolver())
        now = datetime.now(timezone.utc)
        expires = engine.compute_expires_utc(LeaveCategory.CAREGIVER, now)
        assert expires is None


# ===================================================================
# No-config defaults
# ===================================================================

class TestEngineDefaults:
    def test_eligibility_with_no_leave_config(self) -> None:
        """Engine works with sane defaults when no leave policy is loaded."""
        engine = LeaveAdjudicationEngine(PolicyResolver(params={"version": "1.0"}, policy={"version": "1.0"}))
        entry = _make_roster_entry()
        trust = _make_trust_record(
            domain_scores={"healthcare": _make_domain_trust("healthcare", 0.50)},
        )
        result = engine.check_adjudicator_eligibility(
            entry, trust, LeaveCategory.ILLNESS, "APPLICANT-001",
        )
        assert result.eligible is True

    def test_quorum_defaults_to_three(self) -> None:
        engine = LeaveAdjudicationEngine(PolicyResolver(params={"version": "1.0"}, policy={"version": "1.0"}))
        record = LeaveRecord(
            leave_id="L1", actor_id="ACTOR-001", category=LeaveCategory.ILLNESS,
        )
        record.adjudications = [
            LeaveAdjudication("A1", AdjudicationVerdict.APPROVE, "healthcare", 0.5),
            LeaveAdjudication("A2", AdjudicationVerdict.APPROVE, "healthcare", 0.6),
        ]
        result = engine.evaluate_quorum(record)
        assert result.quorum_reached is False  # 2 < 3 default


# ===================================================================
# Adjudicator diversity checks (CX finding regression)
# ===================================================================

class TestAdjudicatorDiversity:
    """Tests for the check_adjudicator_diversity engine method."""

    def test_same_org_same_region_fails(self) -> None:
        """All adjudicators from same org+region: diversity not met."""
        engine = LeaveAdjudicationEngine(_make_resolver())
        entries = {
            "A1": _make_roster_entry("A1", region="EU", organization="Hospital-A"),
            "A2": _make_roster_entry("A2", region="EU", organization="Hospital-A"),
            "A3": _make_roster_entry("A3", region="EU", organization="Hospital-A"),
        }
        violations = engine.check_adjudicator_diversity(entries)
        assert len(violations) == 2  # org + region both fail

    def test_different_orgs_same_region_fails_region(self) -> None:
        """Different orgs but same region: region diversity fails."""
        engine = LeaveAdjudicationEngine(_make_resolver())
        entries = {
            "A1": _make_roster_entry("A1", region="EU", organization="Hospital-A"),
            "A2": _make_roster_entry("A2", region="EU", organization="Hospital-B"),
            "A3": _make_roster_entry("A3", region="EU", organization="Clinic-C"),
        }
        violations = engine.check_adjudicator_diversity(entries)
        # Orgs pass (3 >= 2), region fails (1 < 2)
        assert len(violations) == 1
        assert "region" in violations[0].lower()

    def test_same_org_different_regions_fails_org(self) -> None:
        """Same org but different regions: org diversity fails."""
        engine = LeaveAdjudicationEngine(_make_resolver())
        entries = {
            "A1": _make_roster_entry("A1", region="EU", organization="Hospital-Same"),
            "A2": _make_roster_entry("A2", region="US", organization="Hospital-Same"),
            "A3": _make_roster_entry("A3", region="APAC", organization="Hospital-Same"),
        }
        violations = engine.check_adjudicator_diversity(entries)
        assert len(violations) == 1
        assert "organisation" in violations[0].lower()

    def test_fully_diverse_passes(self) -> None:
        """Different orgs and regions: passes."""
        engine = LeaveAdjudicationEngine(_make_resolver())
        entries = {
            "A1": _make_roster_entry("A1", region="EU", organization="Hospital-A"),
            "A2": _make_roster_entry("A2", region="US", organization="Hospital-B"),
            "A3": _make_roster_entry("A3", region="APAC", organization="Clinic-C"),
        }
        violations = engine.check_adjudicator_diversity(entries)
        assert len(violations) == 0

    def test_empty_entries_passes(self) -> None:
        """No adjudicators → no violations (edge case)."""
        engine = LeaveAdjudicationEngine(_make_resolver())
        violations = engine.check_adjudicator_diversity({})
        assert len(violations) == 0

    def test_two_orgs_two_regions_minimum_passes(self) -> None:
        """Exactly min_organizations=2 and min_regions=2: passes."""
        engine = LeaveAdjudicationEngine(_make_resolver())
        entries = {
            "A1": _make_roster_entry("A1", region="EU", organization="Hospital-A"),
            "A2": _make_roster_entry("A2", region="EU", organization="Hospital-A"),
            "A3": _make_roster_entry("A3", region="US", organization="Hospital-B"),
        }
        violations = engine.check_adjudicator_diversity(entries)
        assert len(violations) == 0  # 2 orgs, 2 regions — meets minimum
