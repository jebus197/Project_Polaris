"""Tests for GenesisService — proves the facade orchestrates correctly."""

import pytest
from pathlib import Path

from genesis.models.mission import DomainType, MissionClass, MissionState
from genesis.models.trust import ActorKind
from genesis.persistence.event_log import EventLog
from genesis.persistence.state_store import StateStore
from genesis.policy.resolver import PolicyResolver
from genesis.review.roster import ActorStatus
from genesis.service import GenesisService


CONFIG_DIR = Path(__file__).resolve().parents[1] / "config"


@pytest.fixture
def resolver() -> PolicyResolver:
    return PolicyResolver.from_config_dir(CONFIG_DIR)


@pytest.fixture
def service(resolver: PolicyResolver) -> GenesisService:
    svc = GenesisService(resolver)
    # Open an epoch so audit-trail recording works (fail-closed requires this)
    svc.open_epoch("test-epoch")
    return svc


def _register_diverse_actors(service: GenesisService) -> None:
    """Register enough actors for R2 selection."""
    actors = [
        ("r1", "NA", "Org1", "claude", "reasoning_model"),
        ("r2", "EU", "Org2", "gpt", "retrieval_augmented"),
        ("r3", "APAC", "Org3", "gemini", "reasoning_model"),
        ("r4", "LATAM", "Org4", "claude", "rule_based_deterministic"),
        ("r5", "AF", "Org5", "gpt", "retrieval_augmented"),
        ("r6", "NA", "Org6", "gemini", "human_reviewer"),
        ("r7", "EU", "Org7", "llama", "reasoning_model"),
    ]
    for id, region, org, family, method in actors:
        service.register_actor(
            actor_id=id, actor_kind=ActorKind.HUMAN,
            region=region, organization=org,
            model_family=family, method_type=method,
            initial_trust=0.5,
        )


class TestActorRegistration:
    def test_register_and_lookup(self, service: GenesisService) -> None:
        result = service.register_actor(
            actor_id="alice", actor_kind=ActorKind.HUMAN,
            region="NA", organization="Org1",
        )
        assert result.success
        assert service.get_actor("alice") is not None

    def test_register_blank_id_fails(self, service: GenesisService) -> None:
        result = service.register_actor(
            actor_id="", actor_kind=ActorKind.HUMAN,
            region="NA", organization="Org1",
        )
        assert not result.success

    def test_register_creates_trust_record(self, service: GenesisService) -> None:
        service.register_actor(
            actor_id="bob", actor_kind=ActorKind.HUMAN,
            region="EU", organization="Org2",
        )
        trust = service.get_trust("bob")
        assert trust is not None
        assert trust.score == 0.10

    def test_quarantine_actor(self, service: GenesisService) -> None:
        service.register_actor(
            actor_id="charlie", actor_kind=ActorKind.MACHINE,
            region="APAC", organization="Org3",
            model_family="gpt", method_type="reasoning_model",
        )
        result = service.quarantine_actor("charlie")
        assert result.success
        assert service.get_actor("charlie").status.value == "quarantined"


class TestMissionLifecycle:
    def test_create_mission(self, service: GenesisService) -> None:
        result = service.create_mission(
            mission_id="M-001", title="Test mission",
            mission_class=MissionClass.DOCUMENTATION_UPDATE,
            domain_type=DomainType.OBJECTIVE,
        )
        assert result.success
        assert result.data["risk_tier"] == "R0"

    def test_duplicate_mission_fails(self, service: GenesisService) -> None:
        service.create_mission(
            mission_id="M-001", title="First",
            mission_class=MissionClass.DOCUMENTATION_UPDATE,
            domain_type=DomainType.OBJECTIVE,
        )
        result = service.create_mission(
            mission_id="M-001", title="Duplicate",
            mission_class=MissionClass.DOCUMENTATION_UPDATE,
            domain_type=DomainType.OBJECTIVE,
        )
        assert not result.success

    def test_submit_mission(self, service: GenesisService) -> None:
        service.create_mission(
            mission_id="M-002", title="Submit test",
            mission_class=MissionClass.DOCUMENTATION_UPDATE,
            domain_type=DomainType.OBJECTIVE,
        )
        result = service.submit_mission("M-002")
        assert result.success
        assert service.get_mission("M-002").state == MissionState.SUBMITTED

    def test_submit_nonexistent_fails(self, service: GenesisService) -> None:
        result = service.submit_mission("M-DOES-NOT-EXIST")
        assert not result.success


class TestFullR0Flow:
    def test_r0_end_to_end(self, service: GenesisService) -> None:
        """Complete R0 mission lifecycle: create → submit → assign → review → approve."""
        _register_diverse_actors(service)

        # Create
        service.create_mission(
            mission_id="M-R0-E2E", title="E2E test",
            mission_class=MissionClass.DOCUMENTATION_UPDATE,
            domain_type=DomainType.OBJECTIVE,
            worker_id="worker_x",
        )

        # Submit
        result = service.submit_mission("M-R0-E2E")
        assert result.success

        # Assign reviewers
        result = service.assign_reviewers("M-R0-E2E", seed="e2e-test")
        assert result.success
        mission = service.get_mission("M-R0-E2E")
        assert len(mission.reviewers) == 1

        # Add evidence
        result = service.add_evidence(
            "M-R0-E2E",
            artifact_hash="sha256:" + "a" * 64,
            signature="ed25519:" + "b" * 64,
        )
        assert result.success

        # Submit review
        reviewer_id = mission.reviewers[0].id
        result = service.submit_review("M-R0-E2E", reviewer_id, "APPROVE")
        assert result.success

        # Complete review
        result = service.complete_review("M-R0-E2E")
        assert result.success
        assert mission.state == MissionState.REVIEW_COMPLETE

        # Approve
        result = service.approve_mission("M-R0-E2E")
        assert result.success
        assert mission.state == MissionState.APPROVED


class TestTrustUpdate:
    def test_update_trust(self, service: GenesisService) -> None:
        service.register_actor(
            actor_id="worker_t", actor_kind=ActorKind.HUMAN,
            region="NA", organization="Org1",
        )
        result = service.update_trust(
            actor_id="worker_t",
            quality=0.9, reliability=0.8, volume=0.4,
            reason="good work", effort=0.5,
        )
        assert result.success
        assert result.data["new_score"] > result.data["old_score"]

    def test_update_trust_nonexistent_fails(self, service: GenesisService) -> None:
        result = service.update_trust(
            actor_id="ghost", quality=0.9, reliability=0.8,
            volume=0.4, reason="no record",
        )
        assert not result.success


class TestEpochIntegration:
    def test_epoch_lifecycle(self, service: GenesisService) -> None:
        # Fixture already opens "test-epoch"
        # Create a mission (should record event in the open epoch)
        service.create_mission(
            mission_id="M-EP", title="Epoch test",
            mission_class=MissionClass.DOCUMENTATION_UPDATE,
            domain_type=DomainType.OBJECTIVE,
        )

        result = service.close_epoch(beacon_round=42)
        assert result.success
        assert result.data["epoch_id"] == "test-epoch"

    def test_close_without_open_fails(self, resolver: PolicyResolver) -> None:
        """Service without an open epoch should fail to close."""
        svc = GenesisService(resolver)
        result = svc.close_epoch(beacon_round=1)
        assert not result.success

    def test_mission_without_epoch_fails_closed(self, resolver: PolicyResolver) -> None:
        """Operations without an open epoch must fail rather than silently drop events."""
        svc = GenesisService(resolver)
        result = svc.create_mission(
            mission_id="M-NO-EPOCH", title="Should fail",
            mission_class=MissionClass.DOCUMENTATION_UPDATE,
            domain_type=DomainType.OBJECTIVE,
        )
        assert not result.success
        assert "epoch" in result.errors[0].lower()

    def test_trust_update_without_epoch_fails_closed(self, resolver: PolicyResolver) -> None:
        """Trust updates without an open epoch must fail closed."""
        svc = GenesisService(resolver)
        svc.register_actor(
            actor_id="test_actor", actor_kind=ActorKind.HUMAN,
            region="NA", organization="Org1",
        )
        result = svc.update_trust(
            actor_id="test_actor", quality=0.9, reliability=0.8,
            volume=0.4, reason="test", effort=0.5,
        )
        assert not result.success
        assert "epoch" in result.errors[0].lower()


class TestHumanGateAPI:
    """Proves R2 human-gate approval path works through the service."""

    def _setup_r2_mission(self, service: GenesisService) -> str:
        """Create an R2 mission through to REVIEW_COMPLETE, ready for human gate.

        R2 requires: 5 reviewers, 4 approvals, 3 regions, 3 orgs,
        2 model families, 2 method types.
        """
        _register_diverse_actors(service)
        # R2 = regulated_analysis
        result = service.create_mission(
            mission_id="M-R2-HG", title="High-risk mission",
            mission_class=MissionClass.REGULATED_ANALYSIS,
            domain_type=DomainType.OBJECTIVE,
            worker_id="worker_x",
        )
        assert result.success, f"create failed: {result.errors}"
        result = service.submit_mission("M-R2-HG")
        assert result.success, f"submit failed: {result.errors}"
        result = service.assign_reviewers("M-R2-HG", seed="hg-test")
        assert result.success, f"assign failed: {result.errors}"
        mission = service.get_mission("M-R2-HG")
        assert len(mission.reviewers) >= 5, f"only {len(mission.reviewers)} reviewers"
        # Add evidence
        result = service.add_evidence(
            "M-R2-HG",
            artifact_hash="sha256:" + "a" * 64,
            signature="ed25519:" + "b" * 64,
        )
        assert result.success
        # Submit all required approvals
        for r in mission.reviewers:
            result = service.submit_review("M-R2-HG", r.id, "APPROVE")
            assert result.success, f"review failed for {r.id}: {result.errors}"
        result = service.complete_review("M-R2-HG")
        assert result.success, f"complete_review failed: {result.errors}"
        assert mission.state == MissionState.REVIEW_COMPLETE
        return "M-R2-HG"

    def test_approve_routes_to_human_gate(self, service: GenesisService) -> None:
        """R2 approve_mission must route through HUMAN_GATE_PENDING."""
        mid = self._setup_r2_mission(service)
        result = service.approve_mission(mid)
        assert result.success
        assert service.get_mission(mid).state == MissionState.HUMAN_GATE_PENDING

    def test_human_gate_approve_completes(self, service: GenesisService) -> None:
        """Human gate approval transitions to APPROVED."""
        mid = self._setup_r2_mission(service)
        service.approve_mission(mid)  # → HUMAN_GATE_PENDING
        result = service.human_gate_approve(mid, approver_id="r1")
        assert result.success
        assert service.get_mission(mid).state == MissionState.APPROVED

    def test_human_gate_reject(self, service: GenesisService) -> None:
        """Human gate rejection transitions to REJECTED."""
        mid = self._setup_r2_mission(service)
        service.approve_mission(mid)
        result = service.human_gate_reject(mid, rejector_id="r1")
        assert result.success
        assert service.get_mission(mid).state == MissionState.REJECTED

    def test_human_gate_rejects_machine_approver(self, service: GenesisService) -> None:
        """Machine actors cannot provide human gate approval."""
        mid = self._setup_r2_mission(service)
        service.approve_mission(mid)
        service.register_actor(
            actor_id="bot", actor_kind=ActorKind.MACHINE,
            region="NA", organization="Org1",
            model_family="gpt", method_type="reasoning_model",
        )
        result = service.human_gate_approve(mid, approver_id="bot")
        assert not result.success
        assert "human" in result.errors[0].lower()

    def test_human_gate_wrong_state_fails(self, service: GenesisService) -> None:
        """human_gate_approve on non-HUMAN_GATE_PENDING state fails."""
        _register_diverse_actors(service)
        service.create_mission(
            mission_id="M-WRONG", title="Wrong state test",
            mission_class=MissionClass.DOCUMENTATION_UPDATE,
            domain_type=DomainType.OBJECTIVE,
        )
        result = service.human_gate_approve("M-WRONG", approver_id="r1")
        assert not result.success


class TestMachineRecertification:
    """Proves machine recertification is enforced in the trust update path."""

    def test_recert_failure_increments_counter(self, service: GenesisService) -> None:
        """Machine with low quality should accumulate recertification failures."""
        service.register_actor(
            actor_id="bot1", actor_kind=ActorKind.MACHINE,
            region="NA", organization="Org1",
            model_family="gpt", method_type="reasoning_model",
        )
        # Low quality + reliability → recert failure
        result = service.update_trust(
            actor_id="bot1", quality=0.1, reliability=0.1,
            volume=0.5, reason="poor performance",
        )
        assert result.success
        assert result.data.get("recertification_issues") is not None
        assert result.data["recertification_failures"] >= 1

    def test_human_not_subject_to_recert(self, service: GenesisService) -> None:
        """Human actors should not trigger recertification checks."""
        service.register_actor(
            actor_id="human1", actor_kind=ActorKind.HUMAN,
            region="NA", organization="Org1",
        )
        result = service.update_trust(
            actor_id="human1", quality=0.1, reliability=0.1,
            volume=0.5, reason="low performance",
        )
        assert result.success
        assert "recertification_issues" not in result.data


class TestPersistenceWiring:
    """Proves service state persists across restarts when wired."""

    def test_round_trip_with_persistence(self, resolver: PolicyResolver, tmp_path: Path) -> None:
        """State survives service restart via StateStore."""
        event_log = EventLog(storage_path=tmp_path / "events.jsonl")
        state_store = StateStore(tmp_path / "state.json")

        svc1 = GenesisService(resolver, event_log=event_log, state_store=state_store)
        svc1.open_epoch("persist-epoch")
        svc1.register_actor(
            actor_id="alice", actor_kind=ActorKind.HUMAN,
            region="EU", organization="OrgA",
        )
        svc1.create_mission(
            mission_id="M-P", title="Persist test",
            mission_class=MissionClass.DOCUMENTATION_UPDATE,
            domain_type=DomainType.OBJECTIVE,
        )
        svc1.close_epoch(beacon_round=99)

        # "Restart" — new service from same storage
        event_log2 = EventLog(storage_path=tmp_path / "events.jsonl")
        state_store2 = StateStore(tmp_path / "state.json")
        svc2 = GenesisService(resolver, event_log=event_log2, state_store=state_store2)

        # State should survive
        assert svc2.get_actor("alice") is not None
        assert svc2.get_mission("M-P") is not None
        assert svc2.get_trust("alice") is not None

    def test_event_log_records_durably(self, resolver: PolicyResolver, tmp_path: Path) -> None:
        """Events written to durable log file."""
        event_log = EventLog(storage_path=tmp_path / "events.jsonl")
        svc = GenesisService(resolver, event_log=event_log)
        svc.open_epoch("log-epoch")
        svc.create_mission(
            mission_id="M-LOG", title="Log test",
            mission_class=MissionClass.DOCUMENTATION_UPDATE,
            domain_type=DomainType.OBJECTIVE,
        )
        assert event_log.count >= 1

        # Reload from file
        log2 = EventLog(storage_path=tmp_path / "events.jsonl")
        assert log2.count >= 1


    def test_mutation_after_restart_no_id_collision(self, resolver: PolicyResolver, tmp_path: Path) -> None:
        """Regression: event-ID counter must resume from persisted log state.

        Previously _event_counter reset to 0 on restart, causing
        'Duplicate event ID' ValueError on the first post-restart mutation.
        """
        event_log = EventLog(storage_path=tmp_path / "events.jsonl")
        state_store = StateStore(tmp_path / "state.json")

        svc1 = GenesisService(resolver, event_log=event_log, state_store=state_store)
        svc1.open_epoch("restart-epoch")
        svc1.create_mission(
            mission_id="M-PRE", title="Pre-restart mission",
            mission_class=MissionClass.DOCUMENTATION_UPDATE,
            domain_type=DomainType.OBJECTIVE,
        )
        events_before = event_log.count
        assert events_before >= 1
        svc1.close_epoch(beacon_round=1)

        # "Restart" — new service from same storage
        event_log2 = EventLog(storage_path=tmp_path / "events.jsonl")
        state_store2 = StateStore(tmp_path / "state.json")
        svc2 = GenesisService(resolver, event_log=event_log2, state_store=state_store2)
        svc2.open_epoch("restart-epoch-2")

        # This must NOT raise ValueError: Duplicate event ID
        result = svc2.create_mission(
            mission_id="M-POST", title="Post-restart mission",
            mission_class=MissionClass.DOCUMENTATION_UPDATE,
            domain_type=DomainType.OBJECTIVE,
        )
        assert result.success, f"Post-restart create_mission failed: {result.errors}"
        assert event_log2.count > events_before

    def test_mutation_after_restart_trust_update(self, resolver: PolicyResolver, tmp_path: Path) -> None:
        """Regression: trust updates must also work after restart without ID collision."""
        event_log = EventLog(storage_path=tmp_path / "events.jsonl")
        state_store = StateStore(tmp_path / "state.json")

        svc1 = GenesisService(resolver, event_log=event_log, state_store=state_store)
        svc1.open_epoch("trust-restart-epoch")
        svc1.register_actor(
            actor_id="worker_r", actor_kind=ActorKind.HUMAN,
            region="NA", organization="Org1",
        )
        svc1.update_trust(
            actor_id="worker_r", quality=0.9, reliability=0.8,
            volume=0.4, reason="pre-restart", effort=0.5,
        )
        svc1.close_epoch(beacon_round=2)

        # "Restart"
        event_log2 = EventLog(storage_path=tmp_path / "events.jsonl")
        state_store2 = StateStore(tmp_path / "state.json")
        svc2 = GenesisService(resolver, event_log=event_log2, state_store=state_store2)
        svc2.open_epoch("trust-restart-epoch-2")

        result = svc2.update_trust(
            actor_id="worker_r", quality=0.7, reliability=0.6,
            volume=0.3, reason="post-restart", effort=0.4,
        )
        assert result.success, f"Post-restart update_trust failed: {result.errors}"


class TestDecommissionRollback:
    """Regression: decommission path must fully rollback on audit failure."""

    def test_roster_status_restored_on_audit_failure(self, resolver: PolicyResolver) -> None:
        """If trust event recording fails, roster status must roll back.

        Previously roster_entry.status was set to DECOMMISSIONED before the
        audit write, but the rollback block did not restore it on failure.
        """
        # Create service WITHOUT an open epoch so audit recording will fail
        svc = GenesisService(resolver)

        # Register a machine actor
        svc.register_actor(
            actor_id="bot_rollback", actor_kind=ActorKind.MACHINE,
            region="NA", organization="Org1",
            model_family="gpt", method_type="reasoning_model",
        )

        # Verify actor starts as ACTIVE
        entry = svc.get_actor("bot_rollback")
        assert entry.status == ActorStatus.ACTIVE

        # Hammer with low-quality updates to reach decommission threshold
        # Each call will fail closed (no epoch), triggering rollback
        decomm = resolver.decommission_rules()
        max_failures = decomm["M_RECERT_FAIL_MAX"]

        for _ in range(max_failures + 5):
            result = svc.update_trust(
                actor_id="bot_rollback", quality=0.0, reliability=0.0,
                volume=0.0, reason="force decommission test",
            )
            # Every call should fail because no epoch is open
            assert not result.success
            assert "epoch" in result.errors[0].lower() or "audit" in result.errors[0].lower()

        # Roster status must still be ACTIVE — not stuck at DECOMMISSIONED
        entry = svc.get_actor("bot_rollback")
        assert entry.status == ActorStatus.ACTIVE, (
            f"Expected ACTIVE after rollback, got {entry.status}"
        )

        # Trust record must be unchanged from initial
        trust = svc.get_trust("bot_rollback")
        assert trust.score == 0.10  # initial default


class TestNoPhantomEpochEvents:
    """Regression: failed durable append must not leave phantom hashes in epoch."""

    def _make_failing_log(self) -> EventLog:
        """Create an EventLog whose append always raises OSError."""
        log = EventLog()  # in-memory only

        def _boom(event):
            raise OSError("simulated disk failure")

        log.append = _boom  # type: ignore[assignment]
        return log

    def test_mission_append_failure_no_phantom_hash(self, resolver: PolicyResolver) -> None:
        """If durable append fails, epoch must contain zero mission hashes.

        Previously epoch hash was inserted first, so a subsequent append failure
        left a phantom hash in the epoch collector while the caller rolled back
        the mission.
        """
        failing_log = self._make_failing_log()
        svc = GenesisService(resolver, event_log=failing_log)
        svc.open_epoch("phantom-test")

        result = svc.create_mission(
            mission_id="M-PHANTOM", title="Should not commit",
            mission_class=MissionClass.DOCUMENTATION_UPDATE,
            domain_type=DomainType.OBJECTIVE,
        )
        assert not result.success
        assert "Event log failure" in result.errors[0]

        # Mission must not exist (caller rollback)
        assert svc.get_mission("M-PHANTOM") is None

        # Epoch must have ZERO mission hashes — no phantom
        counts = svc._epoch_service.epoch_event_counts()
        assert counts.get("mission", 0) == 0, (
            f"Phantom epoch hash: expected 0 mission events, got {counts.get('mission', 0)}"
        )

    def test_trust_append_failure_no_phantom_hash(self, resolver: PolicyResolver) -> None:
        """If durable append fails, epoch must contain zero trust hashes."""
        failing_log = self._make_failing_log()
        svc = GenesisService(resolver, event_log=failing_log)
        svc.open_epoch("phantom-trust-test")

        # Register must succeed (register_actor doesn't go through _record_trust_event)
        svc.register_actor(
            actor_id="worker_phantom", actor_kind=ActorKind.HUMAN,
            region="NA", organization="Org1",
        )

        result = svc.update_trust(
            actor_id="worker_phantom", quality=0.8, reliability=0.7,
            volume=0.3, reason="phantom test", effort=0.2,
        )
        assert not result.success
        assert "Event log failure" in result.errors[0]

        # Trust score must be unchanged (rollback)
        trust = svc.get_trust("worker_phantom")
        assert trust.score == 0.10  # initial

        # Epoch must have ZERO trust hashes — no phantom
        counts = svc._epoch_service.epoch_event_counts()
        assert counts.get("trust", 0) == 0, (
            f"Phantom epoch hash: expected 0 trust events, got {counts.get('trust', 0)}"
        )


class TestStatus:
    def test_status_structure(self, service: GenesisService) -> None:
        status = service.status()
        assert "actors" in status
        assert "missions" in status
        assert "epochs" in status
        assert status["actors"]["total"] == 0
        assert status["missions"]["total"] == 0
