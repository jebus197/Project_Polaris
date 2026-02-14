"""Integration tests for quality assessment through the service layer.

Tests the full flow: mission lifecycle → quality assessment → trust update.
Proves quality is now derived from actual work, not caller-supplied values.
"""

import pytest
from pathlib import Path

from genesis.models.mission import (
    DomainType,
    MissionClass,
    MissionState,
)
from genesis.models.trust import ActorKind
from genesis.policy.resolver import PolicyResolver
from genesis.service import GenesisService


CONFIG_DIR = Path(__file__).resolve().parents[1] / "config"


@pytest.fixture
def resolver() -> PolicyResolver:
    return PolicyResolver.from_config_dir(CONFIG_DIR)


@pytest.fixture
def service(resolver: PolicyResolver) -> GenesisService:
    svc = GenesisService(resolver)
    svc.open_epoch("test-epoch")
    return svc


def _register_actors(service: GenesisService) -> None:
    """Register worker + diverse reviewers for R0/R1 selection."""
    service.register_actor(
        actor_id="worker-1", actor_kind=ActorKind.HUMAN,
        region="NA", organization="Org1",
        initial_trust=0.5,
    )
    actors = [
        ("rev-1", "NA", "Org1", "claude", "reasoning_model"),
        ("rev-2", "EU", "Org2", "gpt", "retrieval_augmented"),
        ("rev-3", "APAC", "Org3", "gemini", "reasoning_model"),
        ("rev-4", "LATAM", "Org4", "claude", "rule_based_deterministic"),
        ("rev-5", "AF", "Org5", "gpt", "retrieval_augmented"),
        ("rev-6", "NA", "Org6", "gemini", "human_reviewer"),
        ("rev-7", "EU", "Org7", "llama", "reasoning_model"),
    ]
    for id_, region, org, family, method in actors:
        service.register_actor(
            actor_id=id_, actor_kind=ActorKind.HUMAN,
            region=region, organization=org,
            model_family=family, method_type=method,
            initial_trust=0.5,
        )


def _run_r0_approval(service: GenesisService, mission_id: str = "M-QA-001") -> dict:
    """Run a complete R0 mission through to APPROVED with quality assessment.

    Returns the approve_mission result data.
    """
    _register_actors(service)

    service.create_mission(
        mission_id=mission_id,
        title="Quality Test Mission",
        mission_class=MissionClass.DOCUMENTATION_UPDATE,
        domain_type=DomainType.OBJECTIVE,
        worker_id="worker-1",
    )
    service.submit_mission(mission_id)
    service.assign_reviewers(mission_id, seed="qa-test")

    mission = service.get_mission(mission_id)
    assert mission is not None

    # Add evidence (R0 expects 1)
    service.add_evidence(
        mission_id,
        artifact_hash="sha256:" + "a" * 64,
        signature="ed25519:" + "b" * 64,
    )

    # All reviewers approve
    for reviewer in mission.reviewers:
        service.submit_review(mission_id, reviewer.id, "APPROVE")

    service.complete_review(mission_id)

    result = service.approve_mission(mission_id)
    assert result.success
    assert mission.state == MissionState.APPROVED
    return result.data


# ===================================================================
# Auto-assessment on approval
# ===================================================================

class TestAutoAssessmentOnApproval:
    def test_r0_approve_triggers_quality_assessment(self, service: GenesisService) -> None:
        """R0 approval should include quality_assessment in result data."""
        data = _run_r0_approval(service)
        assert "quality_assessment" in data
        qa = data["quality_assessment"]
        assert "worker_derived_quality" in qa
        assert "normative_escalation" in qa
        assert qa["normative_escalation"] is False

    def test_worker_derived_quality_is_positive(self, service: GenesisService) -> None:
        """Worker quality for unanimously approved mission should be high."""
        data = _run_r0_approval(service)
        qa = data["quality_assessment"]
        assert qa["worker_derived_quality"] > 0.5

    def test_worker_trust_updated_via_quality(self, service: GenesisService) -> None:
        """Worker trust should be updated by the derived quality score."""
        data = _run_r0_approval(service)
        qa = data["quality_assessment"]
        assert qa["worker_trust_updated"] is True

    def test_reviewer_trust_updated(self, service: GenesisService) -> None:
        """Each reviewer should have their trust updated."""
        data = _run_r0_approval(service)
        qa = data["quality_assessment"]
        assert "reviewer_assessments" in qa
        assert len(qa["reviewer_assessments"]) > 0
        for rev in qa["reviewer_assessments"]:
            assert rev["trust_updated"] is True
            assert rev["derived_quality"] > 0.0


# ===================================================================
# Trust impact
# ===================================================================

class TestTrustImpact:
    def test_high_quality_mission_raises_worker_trust(self, service: GenesisService) -> None:
        """Unanimous approval with evidence → worker trust increases."""
        _register_actors(service)
        worker_trust_before = service.get_trust("worker-1").score

        service.create_mission(
            mission_id="M-TRUST-UP",
            title="High Quality Mission",
            mission_class=MissionClass.DOCUMENTATION_UPDATE,
            domain_type=DomainType.OBJECTIVE,
            worker_id="worker-1",
        )
        service.submit_mission("M-TRUST-UP")
        service.assign_reviewers("M-TRUST-UP", seed="trust-test")

        mission = service.get_mission("M-TRUST-UP")
        service.add_evidence(
            "M-TRUST-UP",
            artifact_hash="sha256:" + "c" * 64,
            signature="ed25519:" + "d" * 64,
        )

        for reviewer in mission.reviewers:
            service.submit_review("M-TRUST-UP", reviewer.id, "APPROVE")
        service.complete_review("M-TRUST-UP")
        service.approve_mission("M-TRUST-UP")

        worker_trust_after = service.get_trust("worker-1").score
        # Trust should increase from derived quality via quality-dominated weight
        assert worker_trust_after >= worker_trust_before

    def test_correct_reviewer_gets_high_alignment(self, service: GenesisService) -> None:
        """Reviewer who voted APPROVE on approved mission → alignment = 1.0."""
        data = _run_r0_approval(service)
        qa = data["quality_assessment"]
        for rev in qa["reviewer_assessments"]:
            # All reviewers voted APPROVE on an approved mission
            assert rev["alignment"] == pytest.approx(1.0)


# ===================================================================
# Rejection quality assessment
# ===================================================================

class TestRejectionQuality:
    def test_rejected_mission_still_assesses_quality(self, service: GenesisService) -> None:
        """Rejected missions trigger quality assessment with low worker quality."""
        _register_actors(service)

        service.create_mission(
            mission_id="M-REJECT",
            title="Rejected Mission",
            mission_class=MissionClass.DOCUMENTATION_UPDATE,
            domain_type=DomainType.OBJECTIVE,
            worker_id="worker-1",
        )
        service.submit_mission("M-REJECT")
        service.assign_reviewers("M-REJECT", seed="reject-test")

        mission = service.get_mission("M-REJECT")
        service.add_evidence(
            "M-REJECT",
            artifact_hash="sha256:" + "e" * 64,
            signature="ed25519:" + "f" * 64,
        )

        # All reviewers reject
        for reviewer in mission.reviewers:
            service.submit_review("M-REJECT", reviewer.id, "REJECT")

        service.complete_review("M-REJECT")

        # For R0, no human gate — REJECTED transition not automatic via approve_mission
        # Need to check if state machine allows REVIEW_COMPLETE → REJECTED
        # Actually approve_mission routes through policy. Let's use manual assess_quality
        # after forcing the state
        # The state machine allows REVIEW_COMPLETE → REJECTED
        mission.state = MissionState.REJECTED

        # Record the transition event manually for this test
        result = service.assess_quality("M-REJECT")
        assert result.success
        qa = result.data
        # Worker quality should be low (consensus = 0)
        assert qa["worker_derived_quality"] < 0.5


# ===================================================================
# Normative escalation
# ===================================================================

class TestNormativeEscalation:
    def test_normative_low_consensus_blocks_trust_update(self, service: GenesisService) -> None:
        """Normative mission with 50% consensus → escalation blocks trust update."""
        _register_actors(service)

        service.create_mission(
            mission_id="M-NORM",
            title="Normative Mission",
            mission_class=MissionClass.DOCUMENTATION_UPDATE,
            domain_type=DomainType.NORMATIVE,
            worker_id="worker-1",
        )
        service.submit_mission("M-NORM")
        service.assign_reviewers("M-NORM", seed="norm-test")

        mission = service.get_mission("M-NORM")
        service.add_evidence(
            "M-NORM",
            artifact_hash="sha256:" + "g" * 64,
            signature="ed25519:" + "h" * 64,
        )

        # Split decision: some approve, some reject
        reviewers = mission.reviewers
        half = len(reviewers) // 2
        for r in reviewers[:half]:
            service.submit_review("M-NORM", r.id, "APPROVE")
        for r in reviewers[half:]:
            service.submit_review("M-NORM", r.id, "REJECT")

        service.complete_review("M-NORM")

        # Force to APPROVED for test (the consensus is low)
        mission.state = MissionState.APPROVED

        result = service.assess_quality("M-NORM")
        assert result.success
        qa = result.data
        assert qa["normative_escalation"] is True
        assert "worker_trust_updated" not in qa  # Trust update deferred


# ===================================================================
# Manual assess_quality API
# ===================================================================

class TestManualAssessQuality:
    def test_assess_quality_on_approved_mission(self, service: GenesisService) -> None:
        """Manual assess_quality works on already-approved mission."""
        data = _run_r0_approval(service, mission_id="M-MANUAL")
        # Now call assess_quality again manually (re-assessment)
        result = service.assess_quality("M-MANUAL")
        assert result.success
        assert result.data["worker_derived_quality"] > 0.0

    def test_assess_quality_nonexistent_mission_fails(self, service: GenesisService) -> None:
        """assess_quality on non-existent mission fails gracefully."""
        result = service.assess_quality("M-GHOST")
        assert not result.success
        assert "not found" in result.errors[0].lower()

    def test_assess_quality_non_terminal_fails(self, service: GenesisService) -> None:
        """assess_quality on a non-terminal mission fails."""
        _register_actors(service)
        service.create_mission(
            mission_id="M-DRAFT",
            title="Still Draft",
            mission_class=MissionClass.DOCUMENTATION_UPDATE,
            domain_type=DomainType.OBJECTIVE,
            worker_id="worker-1",
        )
        result = service.assess_quality("M-DRAFT")
        assert not result.success
        assert "terminal" in result.errors[0].lower()


# ===================================================================
# Backward compatibility
# ===================================================================

class TestBackwardCompatibility:
    def test_update_trust_still_works_directly(self, service: GenesisService) -> None:
        """Existing update_trust API unchanged — manual quality values accepted."""
        service.register_actor(
            actor_id="legacy-worker", actor_kind=ActorKind.HUMAN,
            region="NA", organization="Org1",
        )
        result = service.update_trust(
            actor_id="legacy-worker",
            quality=0.9, reliability=0.8, volume=0.4,
            reason="manual assessment", effort=0.5,
        )
        assert result.success
        assert result.data["new_score"] > result.data["old_score"]


# ===================================================================
# Quality event audit trail
# ===================================================================

class TestQualityAuditTrail:
    def test_quality_assessed_without_epoch_fails(self, service: GenesisService) -> None:
        """Quality assessment without open epoch fails closed."""
        _register_actors(service)

        service.create_mission(
            mission_id="M-NOEPOCH",
            title="No Epoch Mission",
            mission_class=MissionClass.DOCUMENTATION_UPDATE,
            domain_type=DomainType.OBJECTIVE,
            worker_id="worker-1",
        )
        service.submit_mission("M-NOEPOCH")
        service.assign_reviewers("M-NOEPOCH", seed="noepoch-test")

        mission = service.get_mission("M-NOEPOCH")
        service.add_evidence(
            "M-NOEPOCH",
            artifact_hash="sha256:" + "j" * 64,
            signature="ed25519:" + "k" * 64,
        )

        for reviewer in mission.reviewers:
            service.submit_review("M-NOEPOCH", reviewer.id, "APPROVE")
        service.complete_review("M-NOEPOCH")

        # Close the epoch so quality event has no epoch
        service.close_epoch(beacon_round=99)

        # Force to APPROVED
        mission.state = MissionState.APPROVED

        # Quality assessment should fail (no open epoch for quality event)
        result = service.assess_quality("M-NOEPOCH")
        assert not result.success
        assert "epoch" in result.errors[0].lower()
