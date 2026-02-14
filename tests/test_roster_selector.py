"""Tests for actor roster and reviewer selector — proves selection invariants."""

import pytest
from pathlib import Path

from genesis.models.trust import ActorKind
from genesis.models.mission import (
    DomainType,
    Mission,
    MissionClass,
    RiskTier,
)
from genesis.policy.resolver import PolicyResolver
from genesis.review.roster import ActorRoster, ActorStatus, RosterEntry
from genesis.review.selector import ReviewerSelector, SelectionResult


CONFIG_DIR = Path(__file__).resolve().parents[1] / "config"


@pytest.fixture
def resolver() -> PolicyResolver:
    return PolicyResolver.from_config_dir(CONFIG_DIR)


def _entry(
    id: str,
    kind: ActorKind = ActorKind.HUMAN,
    trust: float = 0.5,
    region: str = "NA",
    org: str = "Org1",
    family: str = "claude",
    method: str = "reasoning_model",
    status: ActorStatus = ActorStatus.ACTIVE,
) -> RosterEntry:
    return RosterEntry(
        actor_id=id,
        actor_kind=kind,
        trust_score=trust,
        region=region,
        organization=org,
        model_family=family,
        method_type=method,
        status=status,
    )


def _r0_mission(worker_id: str = "worker_1") -> Mission:
    return Mission(
        mission_id="M-R0",
        mission_title="R0 test",
        mission_class=MissionClass.DOCUMENTATION_UPDATE,
        risk_tier=RiskTier.R0,
        domain_type=DomainType.OBJECTIVE,
        worker_id=worker_id,
    )


def _r2_mission(worker_id: str = "worker_1") -> Mission:
    return Mission(
        mission_id="M-R2",
        mission_title="R2 test",
        mission_class=MissionClass.REGULATED_ANALYSIS,
        risk_tier=RiskTier.R2,
        domain_type=DomainType.MIXED,
        worker_id=worker_id,
    )


# =====================================================================
# Roster Tests
# =====================================================================


class TestRosterRegistration:
    def test_register_and_lookup(self) -> None:
        roster = ActorRoster()
        roster.register(_entry("alice"))
        assert roster.get("alice") is not None
        assert roster.get("alice").actor_id == "alice"

    def test_blank_id_rejected(self) -> None:
        roster = ActorRoster()
        with pytest.raises(ValueError, match="blank"):
            roster.register(_entry(""))

    def test_whitespace_id_rejected(self) -> None:
        roster = ActorRoster()
        with pytest.raises(ValueError, match="blank"):
            roster.register(_entry("   "))

    def test_invalid_trust_rejected(self) -> None:
        roster = ActorRoster()
        with pytest.raises(ValueError, match="Trust score"):
            roster.register(_entry("alice", trust=1.5))
        with pytest.raises(ValueError, match="Trust score"):
            roster.register(_entry("bob", trust=-0.1))

    def test_id_canonicalisation(self) -> None:
        roster = ActorRoster()
        roster.register(_entry("  alice  "))
        assert roster.get("alice") is not None

    def test_overwrite_on_reregister(self) -> None:
        roster = ActorRoster()
        roster.register(_entry("alice", trust=0.3))
        roster.register(_entry("alice", trust=0.9))
        assert roster.get("alice").trust_score == 0.9

    def test_remove(self) -> None:
        roster = ActorRoster()
        roster.register(_entry("alice"))
        roster.remove("alice")
        assert roster.get("alice") is None


class TestRosterFiltering:
    def test_excludes_quarantined(self) -> None:
        roster = ActorRoster()
        roster.register(_entry("alice", status=ActorStatus.ACTIVE))
        roster.register(_entry("bob", status=ActorStatus.QUARANTINED))
        available = roster.available_reviewers()
        assert len(available) == 1
        assert available[0].actor_id == "alice"

    def test_excludes_decommissioned(self) -> None:
        roster = ActorRoster()
        roster.register(_entry("alice", status=ActorStatus.ACTIVE))
        roster.register(_entry("bob", status=ActorStatus.DECOMMISSIONED))
        available = roster.available_reviewers()
        assert len(available) == 1

    def test_includes_probation(self) -> None:
        roster = ActorRoster()
        roster.register(_entry("alice", status=ActorStatus.PROBATION))
        available = roster.available_reviewers()
        assert len(available) == 1

    def test_excludes_by_id(self) -> None:
        roster = ActorRoster()
        roster.register(_entry("alice"))
        roster.register(_entry("bob"))
        available = roster.available_reviewers(exclude_ids={"alice"})
        assert len(available) == 1
        assert available[0].actor_id == "bob"

    def test_min_trust_filter(self) -> None:
        roster = ActorRoster()
        roster.register(_entry("alice", trust=0.3))
        roster.register(_entry("bob", trust=0.8))
        available = roster.available_reviewers(min_trust=0.5)
        assert len(available) == 1
        assert available[0].actor_id == "bob"

    def test_counts(self) -> None:
        roster = ActorRoster()
        roster.register(_entry("h1", kind=ActorKind.HUMAN))
        roster.register(_entry("h2", kind=ActorKind.HUMAN, status=ActorStatus.QUARANTINED))
        roster.register(_entry("m1", kind=ActorKind.MACHINE))
        assert roster.count == 3
        assert roster.active_count == 2  # h1 + m1
        assert roster.human_count == 1  # h1 only (h2 quarantined)


# =====================================================================
# Selector Tests
# =====================================================================


def _make_diverse_roster() -> ActorRoster:
    """Build a roster with enough diversity for R2 selection."""
    roster = ActorRoster()
    entries = [
        _entry("r1", region="NA", org="Org1", family="claude", method="reasoning_model"),
        _entry("r2", region="EU", org="Org2", family="gpt", method="retrieval_augmented"),
        _entry("r3", region="APAC", org="Org3", family="gemini", method="reasoning_model"),
        _entry("r4", region="LATAM", org="Org4", family="claude", method="rule_based_deterministic"),
        _entry("r5", region="AF", org="Org5", family="gpt", method="retrieval_augmented"),
        _entry("r6", region="NA", org="Org6", family="gemini", method="human_reviewer"),
        _entry("r7", region="EU", org="Org7", family="llama", method="reasoning_model"),
    ]
    for e in entries:
        roster.register(e)
    return roster


class TestR0Selection:
    def test_selects_one_reviewer(self, resolver: PolicyResolver) -> None:
        roster = ActorRoster()
        roster.register(_entry("rev_1"))
        roster.register(_entry("rev_2"))

        selector = ReviewerSelector(resolver, roster)
        result = selector.select(_r0_mission(), seed="test-r0")
        assert result.success
        assert len(result.reviewers) == 1

    def test_excludes_worker(self, resolver: PolicyResolver) -> None:
        roster = ActorRoster()
        roster.register(_entry("worker_1"))  # Same as mission worker
        roster.register(_entry("rev_1"))

        selector = ReviewerSelector(resolver, roster)
        result = selector.select(_r0_mission(worker_id="worker_1"), seed="test")
        assert result.success
        assert all(r.id != "worker_1" for r in result.reviewers)

    def test_fails_when_only_worker_available(self, resolver: PolicyResolver) -> None:
        roster = ActorRoster()
        roster.register(_entry("worker_1"))

        selector = ReviewerSelector(resolver, roster)
        result = selector.select(_r0_mission(worker_id="worker_1"), seed="test")
        assert not result.success
        assert "Insufficient" in result.errors[0]


class TestR2Selection:
    def test_selects_diverse_reviewers(self, resolver: PolicyResolver) -> None:
        roster = _make_diverse_roster()
        selector = ReviewerSelector(resolver, roster)
        result = selector.select(_r2_mission(), seed="test-r2")
        assert result.success
        assert len(result.reviewers) >= 5

        # Verify diversity
        families = {r.model_family for r in result.reviewers}
        methods = {r.method_type for r in result.reviewers}
        regions = {r.region for r in result.reviewers}
        orgs = {r.organization for r in result.reviewers}
        assert len(families) >= 2
        assert len(methods) >= 2
        assert len(regions) >= 3
        assert len(orgs) >= 3

    def test_monoculture_pool_fails(self, resolver: PolicyResolver) -> None:
        """A pool with all same family/method cannot satisfy R2."""
        roster = ActorRoster()
        for i in range(10):
            roster.register(
                _entry(f"rev_{i}", region=f"R{i}", org=f"Org{i}",
                       family="claude", method="reasoning_model")
            )

        selector = ReviewerSelector(resolver, roster)
        result = selector.select(_r2_mission(), seed="test")
        assert not result.success
        assert "diversity" in result.errors[0].lower()

    def test_insufficient_pool_fails(self, resolver: PolicyResolver) -> None:
        """Too few candidates for R2."""
        roster = ActorRoster()
        roster.register(_entry("rev_1"))
        roster.register(_entry("rev_2"))

        selector = ReviewerSelector(resolver, roster)
        result = selector.select(_r2_mission(), seed="test")
        assert not result.success


class TestDeterministicSelection:
    def test_same_seed_same_result(self, resolver: PolicyResolver) -> None:
        roster = _make_diverse_roster()
        selector = ReviewerSelector(resolver, roster)

        r1 = selector.select(_r2_mission(), seed="deterministic")
        r2 = selector.select(_r2_mission(), seed="deterministic")

        assert r1.success and r2.success
        ids1 = [r.id for r in r1.reviewers]
        ids2 = [r.id for r in r2.reviewers]
        assert ids1 == ids2

    def test_different_seed_may_differ(self, resolver: PolicyResolver) -> None:
        roster = _make_diverse_roster()
        selector = ReviewerSelector(resolver, roster)

        r1 = selector.select(_r2_mission(), seed="seed_a")
        r2 = selector.select(_r2_mission(), seed="seed_b")

        # Both should succeed; reviewers may or may not differ
        assert r1.success and r2.success


class TestR3Constitutional:
    def test_r3_deferred_to_governance(self, resolver: PolicyResolver) -> None:
        """R3 missions are handled by the governance module, not the selector."""
        roster = _make_diverse_roster()
        selector = ReviewerSelector(resolver, roster)
        mission = Mission(
            mission_id="M-R3",
            mission_title="R3 constitutional",
            mission_class=MissionClass.CONSTITUTIONAL_CHANGE,
            risk_tier=RiskTier.R3,
            domain_type=DomainType.NORMATIVE,
            worker_id="worker_1",
        )
        result = selector.select(mission, seed="test")
        assert not result.success
        assert "governance" in result.errors[0].lower()


class TestQuarantinedExcluded:
    def test_quarantined_never_selected(self, resolver: PolicyResolver) -> None:
        roster = ActorRoster()
        roster.register(_entry("q1", status=ActorStatus.QUARANTINED))
        roster.register(_entry("active_1"))

        selector = ReviewerSelector(resolver, roster)
        result = selector.select(_r0_mission(), seed="test")
        assert result.success
        assert all(r.id != "q1" for r in result.reviewers)

    def test_decommissioned_never_selected(self, resolver: PolicyResolver) -> None:
        roster = ActorRoster()
        roster.register(_entry("d1", status=ActorStatus.DECOMMISSIONED))
        roster.register(_entry("active_1"))

        selector = ReviewerSelector(resolver, roster)
        result = selector.select(_r0_mission(), seed="test")
        assert result.success
        assert all(r.id != "d1" for r in result.reviewers)


class TestMinTrustFilter:
    def test_below_trust_threshold_excluded(self, resolver: PolicyResolver) -> None:
        roster = ActorRoster()
        roster.register(_entry("low", trust=0.1))
        roster.register(_entry("high", trust=0.8))

        selector = ReviewerSelector(resolver, roster)
        result = selector.select(_r0_mission(), seed="test", min_trust=0.5)
        assert result.success
        assert result.reviewers[0].id == "high"
