"""Integration tests for the protected leave system.

End-to-end tests through GenesisService: request, adjudicate, approve,
deny, trust freeze, decay skip, return, persistence round-trip.
"""

import pytest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from genesis.crypto.epoch_service import GENESIS_PREVIOUS_HASH
from genesis.models.domain_trust import DomainTrustScore
from genesis.models.leave import (
    AdjudicationVerdict,
    LeaveCategory,
    LeaveRecord,
    LeaveState,
)
from genesis.models.trust import ActorKind, TrustRecord
from genesis.persistence.event_log import EventLog
from genesis.persistence.state_store import StateStore
from genesis.policy.resolver import PolicyResolver
from genesis.review.roster import ActorStatus
from genesis.service import GenesisService, ServiceResult


# ===================================================================
# Test fixtures
# ===================================================================

def _make_service(
    event_log: EventLog | None = None,
    state_store: StateStore | None = None,
) -> GenesisService:
    """Create a fully configured GenesisService with leave support."""
    config_dir = Path(__file__).parent.parent / "config"
    resolver = PolicyResolver.from_config_dir(config_dir)
    service = GenesisService(
        resolver,
        event_log=event_log,
        state_store=state_store,
    )
    return service


def _setup_leave_scenario(service: GenesisService) -> dict[str, str]:
    """Register an applicant and 3 qualified adjudicators.

    Returns dict with actor IDs.
    """
    # Open epoch for event recording
    service.open_epoch()

    # Register applicant
    service.register_actor(
        "APPLICANT-001", ActorKind.HUMAN,
        region="EU", organization="WorkCorp",
    )

    # Register 3 human adjudicators with healthcare domain trust
    for i in range(1, 4):
        aid = f"DOC-00{i}"
        service.register_actor(
            aid, ActorKind.HUMAN,
            region=["EU", "US", "APAC"][i - 1],
            organization=["Hospital-A", "Hospital-B", "Clinic-C"][i - 1],
        )
        # Build trust above thresholds
        trust = service._trust_records.get(aid)
        if trust:
            trust.score = 0.60
            trust.domain_scores["healthcare"] = DomainTrustScore(
                domain="healthcare", score=0.50, mission_count=10,
            )
        entry = service._roster.get(aid)
        if entry:
            entry.trust_score = 0.60

    return {
        "applicant": "APPLICANT-001",
        "doc1": "DOC-001",
        "doc2": "DOC-002",
        "doc3": "DOC-003",
    }


def _setup_social_services_adjudicators(service: GenesisService) -> list[str]:
    """Register 3 adjudicators with social_services domain trust."""
    aids = []
    for i in range(1, 4):
        aid = f"SW-00{i}"
        service.register_actor(
            aid, ActorKind.HUMAN,
            region=["EU", "US", "APAC"][i - 1],
            organization=["SocServ-A", "SocServ-B", "SocServ-C"][i - 1],
        )
        trust = service._trust_records.get(aid)
        if trust:
            trust.score = 0.55
            trust.domain_scores["social_services"] = DomainTrustScore(
                domain="social_services", score=0.45, mission_count=8,
            )
        entry = service._roster.get(aid)
        if entry:
            entry.trust_score = 0.55
        aids.append(aid)
    return aids


# ===================================================================
# Full approve flow
# ===================================================================

class TestFullApproveFlow:
    def test_three_approves_activates_leave(self) -> None:
        service = _make_service(event_log=EventLog())
        actors = _setup_leave_scenario(service)

        # Request leave
        result = service.request_leave(
            actors["applicant"], LeaveCategory.ILLNESS,
            reason_summary="Medical treatment needed",
        )
        assert result.success is True
        leave_id = result.data["leave_id"]
        assert result.data["state"] == "pending"

        # 3 adjudicators approve
        for doc_key in ["doc1", "doc2", "doc3"]:
            result = service.adjudicate_leave(
                leave_id, actors[doc_key], AdjudicationVerdict.APPROVE,
            )
            assert result.success is True

        # Final result should show approved
        assert result.data["state"] == "active"
        assert result.data["quorum_reached"] is True
        assert result.data["trust_frozen"] is True

        # Verify actor is on leave
        assert service.is_actor_on_leave(actors["applicant"]) is True
        entry = service._roster.get(actors["applicant"])
        assert entry.status == ActorStatus.ON_LEAVE

        # Verify trust was frozen
        record = service.get_leave_record(leave_id)
        assert record.state == LeaveState.ACTIVE
        assert record.trust_score_at_freeze is not None

    def test_approve_with_two_approve_one_deny(self) -> None:
        service = _make_service(event_log=EventLog())
        actors = _setup_leave_scenario(service)

        result = service.request_leave(
            actors["applicant"], LeaveCategory.ILLNESS,
        )
        leave_id = result.data["leave_id"]

        service.adjudicate_leave(leave_id, actors["doc1"], AdjudicationVerdict.APPROVE)
        service.adjudicate_leave(leave_id, actors["doc2"], AdjudicationVerdict.DENY)
        result = service.adjudicate_leave(leave_id, actors["doc3"], AdjudicationVerdict.APPROVE)

        assert result.data["state"] == "active"
        assert result.data["approve_count"] == 2
        assert result.data["deny_count"] == 1


# ===================================================================
# Full deny flow
# ===================================================================

class TestFullDenyFlow:
    def test_three_denies(self) -> None:
        service = _make_service(event_log=EventLog())
        actors = _setup_leave_scenario(service)

        result = service.request_leave(
            actors["applicant"], LeaveCategory.ILLNESS,
        )
        leave_id = result.data["leave_id"]

        for doc_key in ["doc1", "doc2", "doc3"]:
            result = service.adjudicate_leave(
                leave_id, actors[doc_key], AdjudicationVerdict.DENY,
            )

        assert result.data["state"] == "denied"
        assert service.is_actor_on_leave(actors["applicant"]) is False

    def test_two_deny_one_approve_still_denied(self) -> None:
        service = _make_service(event_log=EventLog())
        actors = _setup_leave_scenario(service)

        result = service.request_leave(
            actors["applicant"], LeaveCategory.ILLNESS,
        )
        leave_id = result.data["leave_id"]

        service.adjudicate_leave(leave_id, actors["doc1"], AdjudicationVerdict.DENY)
        service.adjudicate_leave(leave_id, actors["doc2"], AdjudicationVerdict.DENY)
        result = service.adjudicate_leave(leave_id, actors["doc3"], AdjudicationVerdict.APPROVE)

        # 1 approve < 2 required
        assert result.data["state"] == "denied"


# ===================================================================
# Trust freeze verification
# ===================================================================

class TestTrustFreeze:
    def test_decay_skips_on_leave_actor(self) -> None:
        service = _make_service(event_log=EventLog())
        actors = _setup_leave_scenario(service)

        # Set applicant trust and last_active well in the past
        trust = service._trust_records.get(actors["applicant"])
        trust.score = 0.80
        trust.last_active_utc = datetime.now(timezone.utc) - timedelta(days=400)
        # Set domain scores with old last_active
        trust.domain_scores["general"] = DomainTrustScore(
            domain="general", score=0.70, mission_count=5,
            last_active_utc=datetime.now(timezone.utc) - timedelta(days=400),
        )

        # Approve leave
        result = service.request_leave(actors["applicant"], LeaveCategory.ILLNESS)
        leave_id = result.data["leave_id"]
        for doc_key in ["doc1", "doc2", "doc3"]:
            service.adjudicate_leave(leave_id, actors[doc_key], AdjudicationVerdict.APPROVE)

        assert service.is_actor_on_leave(actors["applicant"]) is True

        # Run decay — applicant should be skipped
        score_before = service._trust_records[actors["applicant"]].score
        service.decay_inactive_actors()
        score_after = service._trust_records[actors["applicant"]].score

        assert score_after == score_before  # Trust unchanged

    def test_skill_decay_skips_on_leave_actor(self) -> None:
        """Skill decay also skips actors on protected leave."""
        service = _make_service(event_log=EventLog())
        actors = _setup_leave_scenario(service)

        # Give applicant a skill profile
        from genesis.models.skill import (
            ActorSkillProfile, SkillId, SkillProficiency,
        )
        skill_id = SkillId(domain="software_engineering", skill="python")
        profile = ActorSkillProfile(
            actor_id=actors["applicant"],
            skills={
                skill_id.canonical: SkillProficiency(
                    skill_id=skill_id,
                    proficiency_score=0.80,
                    evidence_count=5,
                    last_demonstrated_utc=datetime.now(timezone.utc) - timedelta(days=200),
                ),
            },
        )
        service._skill_profiles[actors["applicant"]] = profile

        # Approve leave
        result = service.request_leave(actors["applicant"], LeaveCategory.ILLNESS)
        leave_id = result.data["leave_id"]
        for doc_key in ["doc1", "doc2", "doc3"]:
            service.adjudicate_leave(leave_id, actors[doc_key], AdjudicationVerdict.APPROVE)

        # Run skill decay
        old_score = service._skill_profiles[actors["applicant"]].skills[skill_id.canonical].proficiency_score
        service.run_skill_decay(actors["applicant"])
        new_score = service._skill_profiles[actors["applicant"]].skills[skill_id.canonical].proficiency_score

        assert new_score == old_score  # Skill unchanged


# ===================================================================
# Return from leave
# ===================================================================

class TestReturnFromLeave:
    def test_return_restores_active_status(self) -> None:
        service = _make_service(event_log=EventLog())
        actors = _setup_leave_scenario(service)

        result = service.request_leave(actors["applicant"], LeaveCategory.ILLNESS)
        leave_id = result.data["leave_id"]
        for doc_key in ["doc1", "doc2", "doc3"]:
            service.adjudicate_leave(leave_id, actors[doc_key], AdjudicationVerdict.APPROVE)

        assert service.is_actor_on_leave(actors["applicant"]) is True

        # Return
        result = service.return_from_leave(leave_id)
        assert result.success is True
        assert result.data["state"] == "returned"

        assert service.is_actor_on_leave(actors["applicant"]) is False
        entry = service._roster.get(actors["applicant"])
        assert entry.status == ActorStatus.ACTIVE

    def test_return_resets_last_active(self) -> None:
        """On return, last_active_utc resets to now — decay resumes from return."""
        service = _make_service(event_log=EventLog())
        actors = _setup_leave_scenario(service)

        # Set old last_active
        trust = service._trust_records.get(actors["applicant"])
        old_time = datetime.now(timezone.utc) - timedelta(days=365)
        trust.last_active_utc = old_time

        result = service.request_leave(actors["applicant"], LeaveCategory.ILLNESS)
        leave_id = result.data["leave_id"]
        for doc_key in ["doc1", "doc2", "doc3"]:
            service.adjudicate_leave(leave_id, actors[doc_key], AdjudicationVerdict.APPROVE)

        # Return
        before_return = datetime.now(timezone.utc)
        result = service.return_from_leave(leave_id)

        # last_active should be recent, not the old time
        trust = service._trust_records.get(actors["applicant"])
        assert trust.last_active_utc >= before_return

    def test_cannot_return_from_pending(self) -> None:
        service = _make_service(event_log=EventLog())
        actors = _setup_leave_scenario(service)

        result = service.request_leave(actors["applicant"], LeaveCategory.ILLNESS)
        leave_id = result.data["leave_id"]

        result = service.return_from_leave(leave_id)
        assert result.success is False
        assert "ACTIVE" in result.errors[0]

    def test_cannot_return_from_denied(self) -> None:
        service = _make_service(event_log=EventLog())
        actors = _setup_leave_scenario(service)

        result = service.request_leave(actors["applicant"], LeaveCategory.ILLNESS)
        leave_id = result.data["leave_id"]
        for doc_key in ["doc1", "doc2", "doc3"]:
            service.adjudicate_leave(leave_id, actors[doc_key], AdjudicationVerdict.DENY)

        result = service.return_from_leave(leave_id)
        assert result.success is False


# ===================================================================
# Death / memorialisation
# ===================================================================

class TestDeathMemorialisation:
    def test_petition_and_approve_memorialisation(self) -> None:
        """Full death pathway: petition → 3 approvals → memorialised."""
        service = _make_service(event_log=EventLog())
        actors = _setup_leave_scenario(service)

        # Register a petitioner (e.g. colleague)
        service.register_actor(
            "COLLEAGUE-001", ActorKind.HUMAN,
            region="EU", organization="WorkCorp",
        )

        result = service.petition_memorialisation(
            actors["applicant"], "COLLEAGUE-001",
            reason_summary="Actor has passed away",
        )
        assert result.success is True
        leave_id = result.data["leave_id"]
        assert result.data["state"] == "pending"

        # Set up adjudicators with both healthcare + social_services
        for doc_key in ["doc1", "doc2", "doc3"]:
            trust = service._trust_records.get(actors[doc_key])
            if trust:
                trust.domain_scores["social_services"] = DomainTrustScore(
                    domain="social_services", score=0.50, mission_count=8,
                )

        # 3 adjudicators approve
        for doc_key in ["doc1", "doc2", "doc3"]:
            result = service.adjudicate_leave(
                leave_id, actors[doc_key], AdjudicationVerdict.APPROVE,
            )
            assert result.success is True

        assert result.data["state"] == "memorialised"
        assert result.data.get("trust_frozen") is True

        record = service.get_leave_record(leave_id)
        assert record.state == LeaveState.MEMORIALISED
        assert record.memorialised_utc is not None
        assert record.petitioner_id == "COLLEAGUE-001"

        entry = service._roster.get(actors["applicant"])
        assert entry.status == ActorStatus.MEMORIALISED

    def test_cannot_return_from_memorialised(self) -> None:
        """Memorialised accounts can never be reactivated."""
        service = _make_service(event_log=EventLog())
        actors = _setup_leave_scenario(service)

        service.register_actor(
            "COLLEAGUE-002", ActorKind.HUMAN,
            region="EU", organization="WorkCorp",
        )

        result = service.petition_memorialisation(
            actors["applicant"], "COLLEAGUE-002",
        )
        leave_id = result.data["leave_id"]

        for doc_key in ["doc1", "doc2", "doc3"]:
            trust = service._trust_records.get(actors[doc_key])
            if trust:
                trust.domain_scores["social_services"] = DomainTrustScore(
                    domain="social_services", score=0.50, mission_count=8,
                )
            service.adjudicate_leave(
                leave_id, actors[doc_key], AdjudicationVerdict.APPROVE,
            )

        result = service.return_from_leave(leave_id)
        assert result.success is False
        assert "permanently sealed" in result.errors[0]

    def test_death_category_blocked_in_request_leave(self) -> None:
        """DEATH category cannot be self-requested via request_leave()."""
        service = _make_service(event_log=EventLog())
        actors = _setup_leave_scenario(service)

        result = service.request_leave(actors["applicant"], LeaveCategory.DEATH)
        assert result.success is False
        assert "petition_memorialisation" in result.errors[0]

    def test_cannot_self_petition_memorialisation(self) -> None:
        """Cannot petition your own memorialisation."""
        service = _make_service(event_log=EventLog())
        actors = _setup_leave_scenario(service)

        result = service.petition_memorialisation(
            actors["applicant"], actors["applicant"],
        )
        assert result.success is False
        assert "yourself" in result.errors[0].lower()

    def test_machine_cannot_be_memorialised(self) -> None:
        """Only human accounts can be memorialised."""
        service = _make_service(event_log=EventLog())
        service.open_epoch()

        service.register_actor(
            "MACHINE-MEM", ActorKind.MACHINE,
            region="EU", organization="AICorp",
        )
        service.register_actor(
            "PETITIONER-MEM", ActorKind.HUMAN,
            region="EU", organization="WorkCorp",
        )

        result = service.petition_memorialisation("MACHINE-MEM", "PETITIONER-MEM")
        assert result.success is False
        assert "human" in result.errors[0].lower()

    def test_cannot_memorialise_twice(self) -> None:
        """Cannot petition memorialisation for already-memorialised account."""
        service = _make_service(event_log=EventLog())
        actors = _setup_leave_scenario(service)

        service.register_actor(
            "COLLEAGUE-003", ActorKind.HUMAN,
            region="EU", organization="WorkCorp",
        )

        result = service.petition_memorialisation(
            actors["applicant"], "COLLEAGUE-003",
        )
        leave_id = result.data["leave_id"]

        for doc_key in ["doc1", "doc2", "doc3"]:
            trust = service._trust_records.get(actors[doc_key])
            if trust:
                trust.domain_scores["social_services"] = DomainTrustScore(
                    domain="social_services", score=0.50, mission_count=8,
                )
            service.adjudicate_leave(
                leave_id, actors[doc_key], AdjudicationVerdict.APPROVE,
            )

        # Try again
        result = service.petition_memorialisation(
            actors["applicant"], "COLLEAGUE-003",
        )
        assert result.success is False
        assert "already memorialised" in result.errors[0]


# ===================================================================
# Eligibility enforcement
# ===================================================================

class TestEligibilityEnforcement:
    def test_self_adjudication_blocked(self) -> None:
        service = _make_service(event_log=EventLog())
        actors = _setup_leave_scenario(service)

        # Build applicant's trust so they'd otherwise qualify
        trust = service._trust_records.get(actors["applicant"])
        trust.score = 0.60
        trust.domain_scores["healthcare"] = DomainTrustScore(
            domain="healthcare", score=0.50, mission_count=10,
        )

        result = service.request_leave(actors["applicant"], LeaveCategory.ILLNESS)
        leave_id = result.data["leave_id"]

        result = service.adjudicate_leave(
            leave_id, actors["applicant"], AdjudicationVerdict.APPROVE,
        )
        assert result.success is False
        assert "Cannot adjudicate own" in result.errors[0]

    def test_machine_adjudication_blocked(self) -> None:
        service = _make_service(event_log=EventLog())
        actors = _setup_leave_scenario(service)

        # Register a machine with high trust
        service.register_actor(
            "MACHINE-001", ActorKind.MACHINE,
            region="EU", organization="AIOrg",
            model_family="gpt-4", method_type="transformer",
        )
        trust = service._trust_records.get("MACHINE-001")
        trust.score = 0.90
        trust.domain_scores["healthcare"] = DomainTrustScore(
            domain="healthcare", score=0.80,
        )

        result = service.request_leave(actors["applicant"], LeaveCategory.ILLNESS)
        leave_id = result.data["leave_id"]

        result = service.adjudicate_leave(
            leave_id, "MACHINE-001", AdjudicationVerdict.APPROVE,
        )
        assert result.success is False
        assert "Only humans" in result.errors[0]

    def test_duplicate_vote_blocked(self) -> None:
        service = _make_service(event_log=EventLog())
        actors = _setup_leave_scenario(service)

        result = service.request_leave(actors["applicant"], LeaveCategory.ILLNESS)
        leave_id = result.data["leave_id"]

        service.adjudicate_leave(leave_id, actors["doc1"], AdjudicationVerdict.APPROVE)
        result = service.adjudicate_leave(leave_id, actors["doc1"], AdjudicationVerdict.APPROVE)
        assert result.success is False
        assert "already voted" in result.errors[0]

    def test_low_trust_adjudicator_blocked(self) -> None:
        service = _make_service(event_log=EventLog())
        actors = _setup_leave_scenario(service)

        # Lower doc1's trust
        trust = service._trust_records.get(actors["doc1"])
        trust.score = 0.20

        result = service.request_leave(actors["applicant"], LeaveCategory.ILLNESS)
        leave_id = result.data["leave_id"]

        result = service.adjudicate_leave(
            leave_id, actors["doc1"], AdjudicationVerdict.APPROVE,
        )
        assert result.success is False
        assert "Global trust" in result.errors[0]

    def test_no_domain_trust_blocked(self) -> None:
        service = _make_service(event_log=EventLog())
        actors = _setup_leave_scenario(service)

        # Remove doc1's healthcare domain trust
        trust = service._trust_records.get(actors["doc1"])
        trust.domain_scores.clear()

        result = service.request_leave(actors["applicant"], LeaveCategory.ILLNESS)
        leave_id = result.data["leave_id"]

        result = service.adjudicate_leave(
            leave_id, actors["doc1"], AdjudicationVerdict.APPROVE,
        )
        assert result.success is False
        assert "No qualifying domain" in result.errors[0]


# ===================================================================
# Anti-gaming enforcement
# ===================================================================

class TestAntiGamingEnforcement:
    def test_cooldown_enforced(self) -> None:
        service = _make_service(event_log=EventLog())
        actors = _setup_leave_scenario(service)

        # First leave: full approve flow
        result = service.request_leave(actors["applicant"], LeaveCategory.ILLNESS)
        leave_id = result.data["leave_id"]
        for doc_key in ["doc1", "doc2", "doc3"]:
            service.adjudicate_leave(leave_id, actors[doc_key], AdjudicationVerdict.APPROVE)
        service.return_from_leave(leave_id)

        # Immediately request another — should fail cooldown
        result = service.request_leave(actors["applicant"], LeaveCategory.ILLNESS)
        assert result.success is False
        assert any("Cooldown" in e for e in result.errors)

    def test_actor_not_found_fails(self) -> None:
        service = _make_service(event_log=EventLog())
        service.open_epoch()

        result = service.request_leave("NONEXISTENT", LeaveCategory.ILLNESS)
        assert result.success is False
        assert "not found" in result.errors[0]

    def test_quarantined_actor_cannot_request(self) -> None:
        service = _make_service(event_log=EventLog())
        actors = _setup_leave_scenario(service)

        service.quarantine_actor(actors["applicant"])
        result = service.request_leave(actors["applicant"], LeaveCategory.ILLNESS)
        assert result.success is False
        assert "quarantined" in result.errors[0]


# ===================================================================
# Pregnancy and child care — duration limits
# ===================================================================

class TestPregnancyAndChildCare:
    def test_pregnancy_leave_gets_expiry(self) -> None:
        service = _make_service(event_log=EventLog())
        actors = _setup_leave_scenario(service)

        result = service.request_leave(actors["applicant"], LeaveCategory.PREGNANCY)
        leave_id = result.data["leave_id"]
        for doc_key in ["doc1", "doc2", "doc3"]:
            service.adjudicate_leave(leave_id, actors[doc_key], AdjudicationVerdict.APPROVE)

        record = service.get_leave_record(leave_id)
        assert record.state == LeaveState.ACTIVE
        assert record.expires_utc is not None
        assert record.granted_duration_days == 365

    def test_child_care_leave_gets_expiry(self) -> None:
        service = _make_service(event_log=EventLog())
        actors = _setup_leave_scenario(service)

        # Need social_services adjudicators for child_care
        sw_aids = _setup_social_services_adjudicators(service)

        result = service.request_leave(actors["applicant"], LeaveCategory.CHILD_CARE)
        leave_id = result.data["leave_id"]
        for sw_id in sw_aids:
            service.adjudicate_leave(leave_id, sw_id, AdjudicationVerdict.APPROVE)

        record = service.get_leave_record(leave_id)
        assert record.state == LeaveState.ACTIVE
        assert record.expires_utc is not None
        assert record.granted_duration_days == 365

    def test_illness_leave_no_expiry(self) -> None:
        service = _make_service(event_log=EventLog())
        actors = _setup_leave_scenario(service)

        result = service.request_leave(actors["applicant"], LeaveCategory.ILLNESS)
        leave_id = result.data["leave_id"]
        for doc_key in ["doc1", "doc2", "doc3"]:
            service.adjudicate_leave(leave_id, actors[doc_key], AdjudicationVerdict.APPROVE)

        record = service.get_leave_record(leave_id)
        assert record.expires_utc is None
        assert record.granted_duration_days is None

    def test_expired_leave_auto_returned(self) -> None:
        """check_leave_expiries auto-returns expired leaves."""
        service = _make_service(event_log=EventLog())
        actors = _setup_leave_scenario(service)

        result = service.request_leave(actors["applicant"], LeaveCategory.PREGNANCY)
        leave_id = result.data["leave_id"]
        for doc_key in ["doc1", "doc2", "doc3"]:
            service.adjudicate_leave(leave_id, actors[doc_key], AdjudicationVerdict.APPROVE)

        # Manually set expires_utc to the past
        record = service.get_leave_record(leave_id)
        record.expires_utc = datetime.now(timezone.utc) - timedelta(days=1)

        result = service.check_leave_expiries()
        assert result.success is True
        assert result.data["expired_count"] == 1

        record = service.get_leave_record(leave_id)
        assert record.state == LeaveState.RETURNED


# ===================================================================
# Query methods
# ===================================================================

class TestQueryMethods:
    def test_get_leave_record(self) -> None:
        service = _make_service(event_log=EventLog())
        actors = _setup_leave_scenario(service)

        result = service.request_leave(actors["applicant"], LeaveCategory.ILLNESS)
        leave_id = result.data["leave_id"]

        record = service.get_leave_record(leave_id)
        assert record is not None
        assert record.leave_id == leave_id
        assert record.actor_id == actors["applicant"]

    def test_get_leave_record_not_found(self) -> None:
        service = _make_service(event_log=EventLog())
        assert service.get_leave_record("NONEXISTENT") is None

    def test_get_actor_leaves(self) -> None:
        service = _make_service(event_log=EventLog())
        actors = _setup_leave_scenario(service)

        service.request_leave(actors["applicant"], LeaveCategory.ILLNESS)
        leaves = service.get_actor_leaves(actors["applicant"])
        assert len(leaves) == 1

    def test_is_actor_on_leave_false_when_pending(self) -> None:
        service = _make_service(event_log=EventLog())
        actors = _setup_leave_scenario(service)

        service.request_leave(actors["applicant"], LeaveCategory.ILLNESS)
        assert service.is_actor_on_leave(actors["applicant"]) is False

    def test_get_leave_status(self) -> None:
        service = _make_service(event_log=EventLog())
        actors = _setup_leave_scenario(service)

        service.request_leave(actors["applicant"], LeaveCategory.ILLNESS)
        status = service.get_leave_status()
        assert status["total_records"] == 1
        assert status["by_state"]["pending"] == 1

    def test_system_status_includes_leave(self) -> None:
        service = _make_service(event_log=EventLog())
        actors = _setup_leave_scenario(service)

        service.request_leave(actors["applicant"], LeaveCategory.ILLNESS)
        status = service.status()
        assert "leave" in status
        assert status["leave"]["pending_requests"] == 1


# ===================================================================
# Persistence round-trip
# ===================================================================

class TestPersistenceRoundTrip:
    def test_save_and_load_leave_records(self, tmp_path: Path) -> None:
        """Create service → approve leave → save → create new service → verify."""
        store_path = tmp_path / "genesis_state.json"
        log_path = tmp_path / "events.jsonl"

        store = StateStore(store_path)
        log = EventLog(log_path)

        service1 = _make_service(event_log=log, state_store=store)
        actors = _setup_leave_scenario(service1)

        # Request and approve leave
        result = service1.request_leave(actors["applicant"], LeaveCategory.ILLNESS)
        leave_id = result.data["leave_id"]
        for doc_key in ["doc1", "doc2", "doc3"]:
            service1.adjudicate_leave(
                leave_id, actors[doc_key], AdjudicationVerdict.APPROVE,
            )

        assert service1.is_actor_on_leave(actors["applicant"]) is True

        # Create fresh service from same state store
        store2 = StateStore(store_path)
        log2 = EventLog(log_path)
        service2 = _make_service(event_log=log2, state_store=store2)

        # Verify leave record survived
        record = service2.get_leave_record(leave_id)
        assert record is not None
        assert record.state == LeaveState.ACTIVE
        assert record.trust_score_at_freeze is not None
        assert record.actor_id == actors["applicant"]
        assert record.category == LeaveCategory.ILLNESS
        assert len(record.adjudications) == 3

        # Verify actor is still on leave
        entry = service2._roster.get(actors["applicant"])
        assert entry.status == ActorStatus.ON_LEAVE

    def test_leave_records_empty_on_fresh_start(self, tmp_path: Path) -> None:
        store_path = tmp_path / "genesis_state.json"
        store = StateStore(store_path)
        service = _make_service(state_store=store)
        assert len(service._leave_records) == 0


# ===================================================================
# Event recording
# ===================================================================

class TestEventRecording:
    def test_leave_events_recorded(self) -> None:
        log = EventLog()
        service = _make_service(event_log=log)
        actors = _setup_leave_scenario(service)

        result = service.request_leave(actors["applicant"], LeaveCategory.ILLNESS)
        leave_id = result.data["leave_id"]

        # Should have LEAVE_REQUESTED event
        from genesis.persistence.event_log import EventKind
        leave_events = log.events(EventKind.LEAVE_REQUESTED)
        assert len(leave_events) >= 1

    def test_all_leave_event_kinds_used(self) -> None:
        """Full flow produces all leave event kinds."""
        log = EventLog()
        service = _make_service(event_log=log)
        actors = _setup_leave_scenario(service)

        # Request
        result = service.request_leave(actors["applicant"], LeaveCategory.ILLNESS)
        leave_id = result.data["leave_id"]

        # Adjudicate (3 approves → triggers approved)
        for doc_key in ["doc1", "doc2", "doc3"]:
            service.adjudicate_leave(leave_id, actors[doc_key], AdjudicationVerdict.APPROVE)

        # Return
        service.return_from_leave(leave_id)

        from genesis.persistence.event_log import EventKind
        all_events = log.events()
        event_kinds = {e.event_kind for e in all_events}

        assert EventKind.LEAVE_REQUESTED in event_kinds
        assert EventKind.LEAVE_ADJUDICATED in event_kinds
        assert EventKind.LEAVE_APPROVED in event_kinds
        assert EventKind.LEAVE_RETURNED in event_kinds

    def test_no_epoch_fails_closed(self) -> None:
        """Without an open epoch, leave operations fail."""
        service = _make_service(event_log=EventLog())
        # DO NOT open epoch

        service.register_actor(
            "ACTOR-001", ActorKind.HUMAN,
            region="EU", organization="Corp",
        )
        result = service.request_leave("ACTOR-001", LeaveCategory.ILLNESS)
        assert result.success is False
        assert "epoch" in result.errors[0].lower()


# ===================================================================
# Edge cases
# ===================================================================

class TestEdgeCases:
    def test_adjudicate_nonexistent_leave(self) -> None:
        service = _make_service(event_log=EventLog())
        service.open_epoch()
        result = service.adjudicate_leave(
            "NONEXISTENT", "DOC-001", AdjudicationVerdict.APPROVE,
        )
        assert result.success is False

    def test_adjudicate_already_approved_leave(self) -> None:
        service = _make_service(event_log=EventLog())
        actors = _setup_leave_scenario(service)

        result = service.request_leave(actors["applicant"], LeaveCategory.ILLNESS)
        leave_id = result.data["leave_id"]
        for doc_key in ["doc1", "doc2", "doc3"]:
            service.adjudicate_leave(leave_id, actors[doc_key], AdjudicationVerdict.APPROVE)

        # Register 4th doc and try to adjudicate already-active leave
        service.register_actor(
            "DOC-004", ActorKind.HUMAN, region="EU", organization="Hospital-D",
        )
        trust = service._trust_records.get("DOC-004")
        trust.score = 0.60
        trust.domain_scores["healthcare"] = DomainTrustScore(
            domain="healthcare", score=0.50,
        )

        result = service.adjudicate_leave(
            leave_id, "DOC-004", AdjudicationVerdict.APPROVE,
        )
        assert result.success is False
        assert "PENDING" in result.errors[0]

    def test_adjudicator_not_registered(self) -> None:
        service = _make_service(event_log=EventLog())
        actors = _setup_leave_scenario(service)

        result = service.request_leave(actors["applicant"], LeaveCategory.ILLNESS)
        leave_id = result.data["leave_id"]

        result = service.adjudicate_leave(
            leave_id, "GHOST-001", AdjudicationVerdict.APPROVE,
        )
        assert result.success is False
        assert "not found" in result.errors[0]

    def test_abstain_votes_dont_trigger_quorum(self) -> None:
        service = _make_service(event_log=EventLog())
        actors = _setup_leave_scenario(service)

        result = service.request_leave(actors["applicant"], LeaveCategory.ILLNESS)
        leave_id = result.data["leave_id"]

        for doc_key in ["doc1", "doc2", "doc3"]:
            service.adjudicate_leave(leave_id, actors[doc_key], AdjudicationVerdict.ABSTAIN)

        record = service.get_leave_record(leave_id)
        assert record.state == LeaveState.PENDING  # No quorum reached


# ===================================================================
# CX Finding Regression Tests
# ===================================================================

class TestCXFindingRegressions:
    """Regression tests for CX review findings on leave implementation.

    Finding 1 (P1): Machines can request protected leave.
    Finding 2 (P1): Adjudicator diversity constraints not enforced.
    Finding 3 (P1): Trust freeze not enforced in update_trust().
    Finding 4 (P2): Leave return upgrades PROBATION to ACTIVE.
    """

    # ---------------------------------------------------------------
    # Finding 1: Machine applicants must be rejected
    # ---------------------------------------------------------------

    def test_machine_cannot_request_leave(self) -> None:
        """P1 regression: machine actors must not be able to request leave."""
        service = _make_service(event_log=EventLog())
        service.open_epoch()

        service.register_actor(
            "MACHINE-001", ActorKind.MACHINE,
            region="EU", organization="RoboCorp",
        )

        result = service.request_leave("MACHINE-001", LeaveCategory.ILLNESS)
        assert result.success is False
        assert "human" in result.errors[0].lower()

    def test_human_can_still_request_leave(self) -> None:
        """Sanity: human actors can still request leave after machine guard."""
        service = _make_service(event_log=EventLog())
        actors = _setup_leave_scenario(service)

        result = service.request_leave(actors["applicant"], LeaveCategory.ILLNESS)
        assert result.success is True
        assert "leave_id" in result.data

    # ---------------------------------------------------------------
    # Finding 2: Adjudicator diversity enforcement
    # ---------------------------------------------------------------

    def test_same_org_same_region_quorum_does_not_activate(self) -> None:
        """P1 regression: 3 approvals from same org+region must not activate."""
        service = _make_service(event_log=EventLog())
        service.open_epoch()

        # Register applicant
        service.register_actor(
            "APPLICANT-DIV", ActorKind.HUMAN,
            region="EU", organization="WorkCorp",
        )

        # Register 3 adjudicators — SAME org AND region
        for i in range(1, 4):
            aid = f"SAME-DOC-{i}"
            service.register_actor(
                aid, ActorKind.HUMAN,
                region="EU", organization="Hospital-Same",
            )
            trust = service._trust_records.get(aid)
            if trust:
                trust.score = 0.60
                trust.domain_scores["healthcare"] = DomainTrustScore(
                    domain="healthcare", score=0.50, mission_count=10,
                )
            entry = service._roster.get(aid)
            if entry:
                entry.trust_score = 0.60

        result = service.request_leave("APPLICANT-DIV", LeaveCategory.ILLNESS)
        leave_id = result.data["leave_id"]

        # All 3 approve — same org, same region
        for i in range(1, 4):
            result = service.adjudicate_leave(
                leave_id, f"SAME-DOC-{i}", AdjudicationVerdict.APPROVE,
            )
            assert result.success is True

        # Leave should still be PENDING (diversity not met)
        record = service.get_leave_record(leave_id)
        assert record.state == LeaveState.PENDING
        assert result.data.get("diversity_unmet") is not None

    def test_diverse_adjudicators_can_activate(self) -> None:
        """Sanity: adjudicators from different orgs/regions activate normally."""
        service = _make_service(event_log=EventLog())
        actors = _setup_leave_scenario(service)
        # _setup_leave_scenario uses different orgs and regions

        result = service.request_leave(actors["applicant"], LeaveCategory.ILLNESS)
        leave_id = result.data["leave_id"]

        for doc_key in ["doc1", "doc2", "doc3"]:
            service.adjudicate_leave(
                leave_id, actors[doc_key], AdjudicationVerdict.APPROVE,
            )

        record = service.get_leave_record(leave_id)
        assert record.state == LeaveState.ACTIVE

    def test_same_org_different_regions_checks_both(self) -> None:
        """Diversity requires BOTH min_organizations and min_regions."""
        service = _make_service(event_log=EventLog())
        service.open_epoch()

        service.register_actor(
            "APPLICANT-D2", ActorKind.HUMAN,
            region="EU", organization="WorkCorp",
        )

        # 3 adjudicators: SAME org, DIFFERENT regions
        regions = ["EU", "US", "APAC"]
        for i in range(1, 4):
            aid = f"ORGTEST-DOC-{i}"
            service.register_actor(
                aid, ActorKind.HUMAN,
                region=regions[i - 1], organization="Hospital-Same",
            )
            trust = service._trust_records.get(aid)
            if trust:
                trust.score = 0.60
                trust.domain_scores["healthcare"] = DomainTrustScore(
                    domain="healthcare", score=0.50, mission_count=10,
                )
            entry = service._roster.get(aid)
            if entry:
                entry.trust_score = 0.60

        result = service.request_leave("APPLICANT-D2", LeaveCategory.ILLNESS)
        leave_id = result.data["leave_id"]

        for i in range(1, 4):
            result = service.adjudicate_leave(
                leave_id, f"ORGTEST-DOC-{i}", AdjudicationVerdict.APPROVE,
            )

        # Same org (1 < min_organizations=2) → diversity not met
        record = service.get_leave_record(leave_id)
        assert record.state == LeaveState.PENDING

    # ---------------------------------------------------------------
    # Finding 3: Trust freeze enforced in update_trust()
    # ---------------------------------------------------------------

    def test_update_trust_blocked_during_leave(self) -> None:
        """P1 regression: update_trust must fail for on-leave actors."""
        service = _make_service(event_log=EventLog())
        actors = _setup_leave_scenario(service)

        # Approve leave
        result = service.request_leave(actors["applicant"], LeaveCategory.ILLNESS)
        leave_id = result.data["leave_id"]
        for doc_key in ["doc1", "doc2", "doc3"]:
            service.adjudicate_leave(
                leave_id, actors[doc_key], AdjudicationVerdict.APPROVE,
            )

        record = service.get_leave_record(leave_id)
        assert record.state == LeaveState.ACTIVE

        # Attempt to update trust — must fail
        frozen_score = record.trust_score_at_freeze
        result = service.update_trust(
            actors["applicant"], quality=0.95, reliability=0.95,
            volume=1.0, reason="post-leave work",
        )
        assert result.success is False
        assert "protected leave" in result.errors[0].lower()

        # Trust score must be unchanged
        trust = service._trust_records.get(actors["applicant"])
        assert trust.score == frozen_score

    def test_update_trust_works_after_return(self) -> None:
        """Sanity: trust updates resume normally after return from leave."""
        service = _make_service(event_log=EventLog())
        actors = _setup_leave_scenario(service)

        result = service.request_leave(actors["applicant"], LeaveCategory.ILLNESS)
        leave_id = result.data["leave_id"]
        for doc_key in ["doc1", "doc2", "doc3"]:
            service.adjudicate_leave(
                leave_id, actors[doc_key], AdjudicationVerdict.APPROVE,
            )

        # Return from leave
        service.return_from_leave(leave_id)

        # Trust update should now work
        result = service.update_trust(
            actors["applicant"], quality=0.90, reliability=0.90,
            volume=1.0, reason="post-return work",
        )
        assert result.success is True

    # ---------------------------------------------------------------
    # Finding 4: Pre-leave status preserved on return
    # ---------------------------------------------------------------

    def test_probation_actor_returns_to_probation(self) -> None:
        """P2 regression: actor on PROBATION must return to PROBATION, not ACTIVE."""
        service = _make_service(event_log=EventLog())
        actors = _setup_leave_scenario(service)

        # Set applicant to PROBATION
        entry = service._roster.get(actors["applicant"])
        entry.status = ActorStatus.PROBATION

        # Request and approve leave
        result = service.request_leave(actors["applicant"], LeaveCategory.ILLNESS)
        leave_id = result.data["leave_id"]

        for doc_key in ["doc1", "doc2", "doc3"]:
            service.adjudicate_leave(
                leave_id, actors[doc_key], AdjudicationVerdict.APPROVE,
            )

        record = service.get_leave_record(leave_id)
        assert record.state == LeaveState.ACTIVE
        assert record.pre_leave_status == "probation"
        assert entry.status == ActorStatus.ON_LEAVE

        # Return from leave
        result = service.return_from_leave(leave_id)
        assert result.success is True

        # Status must be PROBATION, not ACTIVE
        assert entry.status == ActorStatus.PROBATION

    def test_active_actor_returns_to_active(self) -> None:
        """Sanity: actor on ACTIVE returns to ACTIVE (no regression)."""
        service = _make_service(event_log=EventLog())
        actors = _setup_leave_scenario(service)

        result = service.request_leave(actors["applicant"], LeaveCategory.ILLNESS)
        leave_id = result.data["leave_id"]

        for doc_key in ["doc1", "doc2", "doc3"]:
            service.adjudicate_leave(
                leave_id, actors[doc_key], AdjudicationVerdict.APPROVE,
            )

        service.return_from_leave(leave_id)

        entry = service._roster.get(actors["applicant"])
        assert entry.status == ActorStatus.ACTIVE

    def test_pre_leave_status_persisted(self) -> None:
        """Pre-leave status survives persistence round-trip."""
        import tempfile
        tmpdir = tempfile.mkdtemp()
        store = StateStore(Path(tmpdir) / "state.json")
        service = _make_service(event_log=EventLog(), state_store=store)
        actors = _setup_leave_scenario(service)

        # Set applicant to PROBATION
        entry = service._roster.get(actors["applicant"])
        entry.status = ActorStatus.PROBATION

        result = service.request_leave(actors["applicant"], LeaveCategory.ILLNESS)
        leave_id = result.data["leave_id"]

        for doc_key in ["doc1", "doc2", "doc3"]:
            service.adjudicate_leave(
                leave_id, actors[doc_key], AdjudicationVerdict.APPROVE,
            )

        # Round-trip through state store
        loaded = store.load_leave_records()
        assert leave_id in loaded
        assert loaded[leave_id].pre_leave_status == "probation"

    def test_auto_expiry_restores_pre_leave_status(self) -> None:
        """Expired leave auto-return restores pre-leave status."""
        service = _make_service(event_log=EventLog())
        actors = _setup_leave_scenario(service)

        # Set applicant to PROBATION
        entry = service._roster.get(actors["applicant"])
        entry.status = ActorStatus.PROBATION

        # Use pregnancy (has 365-day limit) to get an expires_utc
        result = service.request_leave(
            actors["applicant"], LeaveCategory.PREGNANCY,
        )
        leave_id = result.data["leave_id"]

        for doc_key in ["doc1", "doc2", "doc3"]:
            service.adjudicate_leave(
                leave_id, actors[doc_key], AdjudicationVerdict.APPROVE,
            )

        # Force expiry by setting expires_utc to past
        record = service.get_leave_record(leave_id)
        record.expires_utc = datetime.now(timezone.utc) - timedelta(days=1)

        # Run expiry sweep
        service.check_leave_expiries()

        assert record.state == LeaveState.RETURNED
        assert entry.status == ActorStatus.PROBATION

    # ---------------------------------------------------------------
    # Finding 5: Memorialised accounts must also freeze trust
    # ---------------------------------------------------------------

    def _petition_and_memorialise(
        self,
        service: GenesisService,
        actors: dict[str, str],
    ) -> str:
        """Helper: petition memorialisation, get 3 approvals → MEMORIALISED."""
        # Register a petitioner
        service.register_actor(
            "PETITIONER-REG", ActorKind.HUMAN,
            region="EU", organization="WorkCorp",
        )

        result = service.petition_memorialisation(
            actors["applicant"], "PETITIONER-REG",
            reason_summary="Passed away",
        )
        assert result.success is True
        leave_id = result.data["leave_id"]

        # Ensure adjudicators have social_services domain (death requires both)
        for doc_key in ["doc1", "doc2", "doc3"]:
            trust = service._trust_records.get(actors[doc_key])
            if trust and "social_services" not in trust.domain_scores:
                trust.domain_scores["social_services"] = DomainTrustScore(
                    domain="social_services", score=0.50, mission_count=8,
                )

        for doc_key in ["doc1", "doc2", "doc3"]:
            service.adjudicate_leave(
                leave_id, actors[doc_key], AdjudicationVerdict.APPROVE,
            )

        record = service.get_leave_record(leave_id)
        assert record.state == LeaveState.MEMORIALISED
        return leave_id

    def test_memorialised_blocks_trust_update(self) -> None:
        """P1 regression: update_trust must fail for memorialised actors."""
        service = _make_service(event_log=EventLog())
        actors = _setup_leave_scenario(service)

        leave_id = self._petition_and_memorialise(service, actors)

        # Trust update must be blocked
        trust_before = service._trust_records[actors["applicant"]].score
        result = service.update_trust(
            actors["applicant"], quality=0.95, reliability=0.95,
            volume=1.0, reason="should be blocked",
        )
        assert result.success is False
        assert "protected leave" in result.errors[0].lower()
        assert service._trust_records[actors["applicant"]].score == trust_before

    def test_memorialised_skips_trust_decay(self) -> None:
        """P1 regression: decay_inactive_actors must skip memorialised actors."""
        service = _make_service(event_log=EventLog())
        actors = _setup_leave_scenario(service)

        leave_id = self._petition_and_memorialise(service, actors)

        trust_before = service._trust_records[actors["applicant"]].score
        service.decay_inactive_actors()
        trust_after = service._trust_records[actors["applicant"]].score
        assert trust_after == trust_before

    def test_memorialised_skips_skill_decay(self) -> None:
        """P1 regression: run_skill_decay must skip memorialised actors."""
        service = _make_service(event_log=EventLog())
        actors = _setup_leave_scenario(service)

        # Give applicant a skill profile via service API
        from genesis.models.skill import SkillId, SkillProficiency
        service.update_actor_skills(actors["applicant"], [
            SkillProficiency(
                skill_id=SkillId("software_engineering", "python"),
                proficiency_score=0.80,
                evidence_count=10,
            ),
        ])

        leave_id = self._petition_and_memorialise(service, actors)

        # Run skill decay — should skip memorialised actor
        profile_before = service.get_actor_skills(actors["applicant"])
        skill_key = "software_engineering:python"
        skill_before = profile_before.skills[skill_key].proficiency_score
        service.run_skill_decay()
        profile_after = service.get_actor_skills(actors["applicant"])
        skill_after = profile_after.skills["software_engineering:python"].proficiency_score
        assert skill_after == skill_before

    def test_is_actor_on_leave_includes_memorialised(self) -> None:
        """is_actor_on_leave returns True for both ACTIVE and MEMORIALISED."""
        service = _make_service(event_log=EventLog())
        actors = _setup_leave_scenario(service)

        # First test with regular ACTIVE leave
        result = service.request_leave(actors["applicant"], LeaveCategory.ILLNESS)
        leave_id = result.data["leave_id"]
        for doc_key in ["doc1", "doc2", "doc3"]:
            service.adjudicate_leave(
                leave_id, actors[doc_key], AdjudicationVerdict.APPROVE,
            )

        # ACTIVE → on leave
        assert service.is_actor_on_leave(actors["applicant"]) is True

        # Return, then memorialise
        service.return_from_leave(leave_id)
        assert service.is_actor_on_leave(actors["applicant"]) is False

        leave_id2 = self._petition_and_memorialise(service, actors)
        # MEMORIALISED → still on leave (trust frozen forever)
        assert service.is_actor_on_leave(actors["applicant"]) is True

    # ---------------------------------------------------------------
    # Finding 6: Legacy state compat — "permanent" maps to "memorialised"
    # ---------------------------------------------------------------

    def test_legacy_permanent_state_loads_as_memorialised(self, tmp_path: Path) -> None:
        """Legacy 'permanent' leave records must load as MEMORIALISED."""
        import json
        legacy_state = {
            "leave_records": {
                "LEAVE-000001": {
                    "leave_id": "LEAVE-000001",
                    "actor_id": "ACTOR-LEGACY",
                    "category": "illness",
                    "state": "permanent",
                    "reason_summary": "legacy record",
                    "adjudications": [],
                    "domain_scores_at_freeze": {},
                },
            },
        }
        state_file = tmp_path / "legacy_state.json"
        state_file.write_text(json.dumps(legacy_state))
        store = StateStore(state_file)
        records = store.load_leave_records()
        assert "LEAVE-000001" in records
        assert records["LEAVE-000001"].state == LeaveState.MEMORIALISED

    # ---------------------------------------------------------------
    # Finding 7: return_from_leave rollback must restore domain timestamps
    # ---------------------------------------------------------------

    def test_failed_return_restores_domain_timestamps(self) -> None:
        """Failed return (no epoch) must not mutate domain last_active_utc."""
        service = _make_service(event_log=EventLog())
        actors = _setup_leave_scenario(service)

        # Give applicant domain trust so there are domain timestamps
        trust = service._trust_records.get(actors["applicant"])
        original_domain_ts = {}
        for domain, ds in trust.domain_scores.items():
            if hasattr(ds, "last_active_utc"):
                original_domain_ts[domain] = ds.last_active_utc

        # Request and approve leave
        result = service.request_leave(actors["applicant"], LeaveCategory.ILLNESS)
        leave_id = result.data["leave_id"]
        for doc_key in ["doc1", "doc2", "doc3"]:
            service.adjudicate_leave(
                leave_id, actors[doc_key], AdjudicationVerdict.APPROVE,
            )

        # Close epoch so return will fail
        service.close_epoch(beacon_round=1)

        # Attempt return — should fail closed
        result = service.return_from_leave(leave_id)
        assert result.success is False

        # Domain timestamps must be unchanged (rolled back)
        for domain, old_ts in original_domain_ts.items():
            ds = trust.domain_scores.get(domain)
            if ds and hasattr(ds, "last_active_utc"):
                assert ds.last_active_utc == old_ts, (
                    f"Domain {domain} last_active_utc was mutated despite failed return"
                )

    # ---------------------------------------------------------------
    # Finding 8: Duplicate death petitions blocked
    # ---------------------------------------------------------------

    def test_duplicate_death_petition_blocked(self) -> None:
        """Second death petition for same actor must be rejected while first is pending."""
        service = _make_service(event_log=EventLog())
        actors = _setup_leave_scenario(service)

        service.register_actor(
            "PETITIONER-DUP1", ActorKind.HUMAN,
            region="EU", organization="WorkCorp",
        )
        service.register_actor(
            "PETITIONER-DUP2", ActorKind.HUMAN,
            region="US", organization="OtherCorp",
        )

        # First petition succeeds
        result = service.petition_memorialisation(
            actors["applicant"], "PETITIONER-DUP1",
        )
        assert result.success is True

        # Second petition for same actor rejected
        result = service.petition_memorialisation(
            actors["applicant"], "PETITIONER-DUP2",
        )
        assert result.success is False
        assert "already has an active death" in result.errors[0]

    def test_adjudicate_rejects_already_memorialised_actor(self) -> None:
        """If actor is memorialised via one record, another pending death record can't adjudicate."""
        service = _make_service(event_log=EventLog())
        actors = _setup_leave_scenario(service)

        service.register_actor(
            "PETITIONER-ADJ", ActorKind.HUMAN,
            region="EU", organization="WorkCorp",
        )

        # Create first petition and memorialise
        result = service.petition_memorialisation(
            actors["applicant"], "PETITIONER-ADJ",
        )
        leave_id1 = result.data["leave_id"]

        for doc_key in ["doc1", "doc2", "doc3"]:
            trust = service._trust_records.get(actors[doc_key])
            if trust and "social_services" not in trust.domain_scores:
                trust.domain_scores["social_services"] = DomainTrustScore(
                    domain="social_services", score=0.50, mission_count=8,
                )

        for doc_key in ["doc1", "doc2", "doc3"]:
            service.adjudicate_leave(
                leave_id1, actors[doc_key], AdjudicationVerdict.APPROVE,
            )

        # Actor is now memorialised
        entry = service._roster.get(actors["applicant"])
        assert entry.status == ActorStatus.MEMORIALISED

        # Manually inject a stale pending death record (simulating race condition)
        from genesis.models.leave import LeaveRecord as LR
        stale_record = LR(
            leave_id="LEAVE-STALE",
            actor_id=actors["applicant"],
            category=LeaveCategory.DEATH,
            state=LeaveState.PENDING,
            petitioner_id="PETITIONER-ADJ",
        )
        service._leave_records["LEAVE-STALE"] = stale_record

        # Trying to adjudicate the stale record should fail
        result = service.adjudicate_leave(
            "LEAVE-STALE", actors["doc1"], AdjudicationVerdict.APPROVE,
        )
        assert result.success is False
        assert "already memorialised" in result.errors[0]

    # ---------------------------------------------------------------
    # Finding 9: max_adjudicators cap enforced
    # ---------------------------------------------------------------

    def test_max_adjudicators_cap_enforced(self) -> None:
        """Adjudication must be rejected when max_adjudicators reached."""
        service = _make_service(event_log=EventLog())
        actors = _setup_leave_scenario(service)

        # Request leave
        result = service.request_leave(actors["applicant"], LeaveCategory.ILLNESS)
        leave_id = result.data["leave_id"]

        # Get max_adjudicators from config
        adj_config = service._resolver.leave_adjudication_config()
        max_adj = adj_config.get("max_adjudicators", 5)

        # Register enough adjudicators to exceed the cap
        registered_docs = []
        for i in range(max_adj + 2):
            doc_id = f"ADJ-CAP-{i:03d}"
            service.register_actor(
                doc_id, ActorKind.HUMAN,
                region=f"REGION-{i % 3}", organization=f"ORG-{i % 3}",
            )
            # Give them domain trust in healthcare
            service.update_trust(
                doc_id, quality=0.90, reliability=0.90,
                volume=1.0, reason="setup",
            )
            trust = service._trust_records.get(doc_id)
            if trust:
                trust.domain_scores["healthcare"] = DomainTrustScore(
                    domain="healthcare", score=0.50, mission_count=8,
                )
            registered_docs.append(doc_id)

        # Submit max_adj adjudications — all should succeed
        for i in range(max_adj):
            result = service.adjudicate_leave(
                leave_id, registered_docs[i], AdjudicationVerdict.ABSTAIN,
            )
            assert result.success is True, f"Adjudication {i} failed: {result.errors}"

        # Next adjudication should be rejected (cap reached)
        result = service.adjudicate_leave(
            leave_id, registered_docs[max_adj], AdjudicationVerdict.APPROVE,
        )
        assert result.success is False
        assert "cap reached" in result.errors[0].lower()
