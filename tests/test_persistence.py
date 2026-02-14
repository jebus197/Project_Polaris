"""Tests for persistence layer — proves event log and state store work correctly."""

import pytest
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from genesis.models.mission import (
    DomainType,
    EvidenceRecord,
    Mission,
    MissionClass,
    MissionState,
    ReviewDecision,
    ReviewDecisionVerdict,
    Reviewer,
    RiskTier,
)
from genesis.models.trust import ActorKind, TrustRecord
from genesis.persistence.event_log import EventLog, EventKind, EventRecord
from genesis.persistence.state_store import StateStore
from genesis.review.roster import ActorRoster, ActorStatus, RosterEntry
from genesis.crypto.epoch_service import GENESIS_PREVIOUS_HASH


# =====================================================================
# EventRecord Tests
# =====================================================================


class TestEventRecord:
    def test_create_produces_hash(self) -> None:
        event = EventRecord.create(
            event_id="E-001",
            event_kind=EventKind.MISSION_CREATED,
            actor_id="alice",
            payload={"mission_id": "M-001"},
        )
        assert event.event_hash.startswith("sha256:")
        assert len(event.event_hash) == 71  # "sha256:" + 64 hex chars

    def test_deterministic_hash(self) -> None:
        ts = datetime(2026, 2, 14, 12, 0, tzinfo=timezone.utc)
        e1 = EventRecord.create("E-1", EventKind.ACTOR_REGISTERED, "bob", {"x": 1}, ts)
        e2 = EventRecord.create("E-1", EventKind.ACTOR_REGISTERED, "bob", {"x": 1}, ts)
        assert e1.event_hash == e2.event_hash

    def test_different_payloads_different_hashes(self) -> None:
        ts = datetime(2026, 2, 14, 12, 0, tzinfo=timezone.utc)
        e1 = EventRecord.create("E-1", EventKind.TRUST_UPDATED, "bob", {"score": 0.5}, ts)
        e2 = EventRecord.create("E-1", EventKind.TRUST_UPDATED, "bob", {"score": 0.9}, ts)
        assert e1.event_hash != e2.event_hash


# =====================================================================
# EventLog Tests
# =====================================================================


class TestEventLog:
    def test_append_and_count(self) -> None:
        log = EventLog()
        event = EventRecord.create("E-1", EventKind.MISSION_CREATED, "alice", {})
        log.append(event)
        assert log.count == 1

    def test_duplicate_id_rejected(self) -> None:
        log = EventLog()
        event = EventRecord.create("E-1", EventKind.MISSION_CREATED, "alice", {})
        log.append(event)
        with pytest.raises(ValueError, match="Duplicate"):
            log.append(event)

    def test_filter_by_kind(self) -> None:
        log = EventLog()
        log.append(EventRecord.create("E-1", EventKind.MISSION_CREATED, "alice", {}))
        log.append(EventRecord.create("E-2", EventKind.TRUST_UPDATED, "bob", {}))
        log.append(EventRecord.create("E-3", EventKind.MISSION_CREATED, "charlie", {}))

        missions = log.events(kind=EventKind.MISSION_CREATED)
        assert len(missions) == 2
        trust = log.events(kind=EventKind.TRUST_UPDATED)
        assert len(trust) == 1

    def test_event_hashes(self) -> None:
        log = EventLog()
        log.append(EventRecord.create("E-1", EventKind.MISSION_CREATED, "alice", {}))
        log.append(EventRecord.create("E-2", EventKind.TRUST_UPDATED, "bob", {}))

        hashes = log.event_hashes()
        assert len(hashes) == 2
        assert all(h.startswith("sha256:") for h in hashes)

    def test_last_event(self) -> None:
        log = EventLog()
        assert log.last_event is None
        log.append(EventRecord.create("E-1", EventKind.MISSION_CREATED, "alice", {}))
        assert log.last_event.event_id == "E-1"

    def test_file_persistence(self, tmp_path: Path) -> None:
        """Events persist to file and can be loaded back."""
        log_path = tmp_path / "events.jsonl"

        # Write events
        log1 = EventLog(storage_path=log_path)
        log1.append(EventRecord.create("E-1", EventKind.MISSION_CREATED, "alice", {"a": 1}))
        log1.append(EventRecord.create("E-2", EventKind.TRUST_UPDATED, "bob", {"b": 2}))

        # Load from file
        log2 = EventLog(storage_path=log_path)
        assert log2.count == 2
        assert log2.events()[0].event_id == "E-1"
        assert log2.events()[1].event_id == "E-2"

    def test_events_since(self) -> None:
        log = EventLog()
        ts1 = datetime(2026, 2, 14, 10, 0, tzinfo=timezone.utc)
        ts2 = datetime(2026, 2, 14, 12, 0, tzinfo=timezone.utc)
        ts3 = datetime(2026, 2, 14, 14, 0, tzinfo=timezone.utc)
        log.append(EventRecord.create("E-1", EventKind.MISSION_CREATED, "a", {}, ts1))
        log.append(EventRecord.create("E-2", EventKind.MISSION_CREATED, "b", {}, ts2))
        log.append(EventRecord.create("E-3", EventKind.TRUST_UPDATED, "c", {}, ts3))

        # Events since noon
        recent = log.events_since("2026-02-14T12:00:00Z")
        assert len(recent) == 2


# =====================================================================
# StateStore Tests
# =====================================================================


class TestStateStoreRoster:
    def test_save_and_load_roster(self, tmp_path: Path) -> None:
        store = StateStore(tmp_path / "state.json")

        roster = ActorRoster()
        roster.register(RosterEntry(
            actor_id="alice", actor_kind=ActorKind.HUMAN,
            trust_score=0.75, region="EU", organization="Org1",
            model_family="human_reviewer", method_type="human_reviewer",
        ))
        roster.register(RosterEntry(
            actor_id="bot1", actor_kind=ActorKind.MACHINE,
            trust_score=0.5, region="NA", organization="Org2",
            model_family="gpt", method_type="reasoning_model",
            status=ActorStatus.QUARANTINED,
        ))

        store.save_roster(roster)

        # Load into fresh store
        store2 = StateStore(tmp_path / "state.json")
        loaded = store2.load_roster()
        assert loaded.count == 2
        assert loaded.get("alice").trust_score == 0.75
        assert loaded.get("bot1").status == ActorStatus.QUARANTINED


class TestStateStoreTrust:
    def test_save_and_load_trust(self, tmp_path: Path) -> None:
        store = StateStore(tmp_path / "state.json")

        records = {
            "alice": TrustRecord(
                actor_id="alice", actor_kind=ActorKind.HUMAN,
                score=0.8, quality=0.9, reliability=0.85,
                volume=0.3, effort=0.6,
            ),
        }

        store.save_trust_records(records)

        store2 = StateStore(tmp_path / "state.json")
        loaded = store2.load_trust_records()
        assert "alice" in loaded
        assert loaded["alice"].score == 0.8
        assert loaded["alice"].effort == 0.6


class TestStateStoreMissions:
    def test_save_and_load_missions(self, tmp_path: Path) -> None:
        store = StateStore(tmp_path / "state.json")

        missions = {
            "M-001": Mission(
                mission_id="M-001",
                mission_title="Test mission",
                mission_class=MissionClass.DOCUMENTATION_UPDATE,
                risk_tier=RiskTier.R0,
                domain_type=DomainType.OBJECTIVE,
                state=MissionState.IN_REVIEW,
                worker_id="worker_1",
                reviewers=[
                    Reviewer(
                        id="rev_1", model_family="claude",
                        method_type="reasoning_model",
                        region="NA", organization="Org1",
                    ),
                ],
                review_decisions=[
                    ReviewDecision(
                        reviewer_id="rev_1",
                        decision=ReviewDecisionVerdict.APPROVE,
                    ),
                ],
                evidence=[
                    EvidenceRecord(
                        artifact_hash="sha256:" + "a" * 64,
                        signature="ed25519:" + "b" * 64,
                    ),
                ],
            ),
        }

        store.save_missions(missions)

        store2 = StateStore(tmp_path / "state.json")
        loaded = store2.load_missions()
        assert "M-001" in loaded
        m = loaded["M-001"]
        assert m.state == MissionState.IN_REVIEW
        assert len(m.reviewers) == 1
        assert len(m.review_decisions) == 1
        assert len(m.evidence) == 1
        assert m.evidence[0].artifact_hash == "sha256:" + "a" * 64


class TestStateStoreEpoch:
    def test_save_and_load_epoch_state(self, tmp_path: Path) -> None:
        store = StateStore(tmp_path / "state.json")
        store.save_epoch_state("sha256:" + "f" * 64, 42)

        store2 = StateStore(tmp_path / "state.json")
        prev_hash, count = store2.load_epoch_state()
        assert prev_hash == "sha256:" + "f" * 64
        assert count == 42

    def test_default_epoch_state(self, tmp_path: Path) -> None:
        store = StateStore(tmp_path / "empty_state.json")
        prev_hash, count = store.load_epoch_state()
        assert prev_hash == GENESIS_PREVIOUS_HASH
        assert count == 0


class TestStateStoreEmpty:
    def test_empty_store(self, tmp_path: Path) -> None:
        store = StateStore(tmp_path / "nonexistent.json")
        assert store.load_roster().count == 0
        assert len(store.load_missions()) == 0
        assert len(store.load_trust_records()) == 0
