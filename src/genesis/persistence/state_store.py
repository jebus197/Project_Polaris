"""State store — JSON-based persistence for Genesis runtime state.

Stores and recovers:
- Actor roster (all registered actors with trust scores)
- Mission state (all missions with their current lifecycle state)
- Reviewer quality assessment histories (sliding windows for calibration)
- Epoch chain state (previous hash, committed record count)

This is a simple file-based store suitable for single-node deployment.
Production deployments would replace this with a database backend
while keeping the same interface.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

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
from genesis.models.quality import ReviewerQualityAssessment
from genesis.models.trust import ActorKind, TrustRecord
from genesis.review.roster import ActorRoster, ActorStatus, RosterEntry


class StateStore:
    """JSON file-based state persistence.

    Usage:
        store = StateStore(Path("data/genesis_state.json"))
        store.save_roster(roster)
        store.save_missions(missions)
        store.save_epoch_state(previous_hash, committed_count)

        # On recovery:
        roster = store.load_roster()
        missions = store.load_missions()
        prev_hash, count = store.load_epoch_state()
    """

    def __init__(self, storage_path: Path) -> None:
        self._path = storage_path
        self._state: dict[str, Any] = {}
        if storage_path.exists():
            self._load()

    def _load(self) -> None:
        with self._path.open("r", encoding="utf-8") as f:
            self._state = json.load(f)

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("w", encoding="utf-8") as f:
            json.dump(self._state, f, indent=2, sort_keys=True, ensure_ascii=False)

    # ------------------------------------------------------------------
    # Roster persistence
    # ------------------------------------------------------------------

    def save_roster(self, roster: ActorRoster) -> None:
        """Serialize the actor roster to state."""
        entries = []
        for actor in roster.all_actors():
            entries.append({
                "actor_id": actor.actor_id,
                "actor_kind": actor.actor_kind.value,
                "trust_score": actor.trust_score,
                "region": actor.region,
                "organization": actor.organization,
                "model_family": actor.model_family,
                "method_type": actor.method_type,
                "status": actor.status.value,
            })
        self._state["roster"] = entries
        self._save()

    def load_roster(self) -> ActorRoster:
        """Deserialize the actor roster from state."""
        roster = ActorRoster()
        for data in self._state.get("roster", []):
            entry = RosterEntry(
                actor_id=data["actor_id"],
                actor_kind=ActorKind(data["actor_kind"]),
                trust_score=data["trust_score"],
                region=data["region"],
                organization=data["organization"],
                model_family=data["model_family"],
                method_type=data["method_type"],
                status=ActorStatus(data["status"]),
            )
            roster.register(entry)
        return roster

    # ------------------------------------------------------------------
    # Trust record persistence
    # ------------------------------------------------------------------

    def save_trust_records(self, records: dict[str, TrustRecord]) -> None:
        """Serialize trust records to state."""
        entries = {}
        for actor_id, record in records.items():
            entries[actor_id] = {
                "actor_id": record.actor_id,
                "actor_kind": record.actor_kind.value,
                "score": record.score,
                "quality": record.quality,
                "reliability": record.reliability,
                "volume": record.volume,
                "effort": record.effort,
                "quarantined": record.quarantined,
                "decommissioned": record.decommissioned,
            }
        self._state["trust_records"] = entries
        self._save()

    def load_trust_records(self) -> dict[str, TrustRecord]:
        """Deserialize trust records from state."""
        records = {}
        for actor_id, data in self._state.get("trust_records", {}).items():
            record = TrustRecord(
                actor_id=data["actor_id"],
                actor_kind=ActorKind(data["actor_kind"]),
                score=data["score"],
                quality=data.get("quality", 0.0),
                reliability=data.get("reliability", 0.0),
                volume=data.get("volume", 0.0),
                effort=data.get("effort", 0.0),
            )
            record.quarantined = data.get("quarantined", False)
            record.decommissioned = data.get("decommissioned", False)
            records[actor_id] = record
        return records

    # ------------------------------------------------------------------
    # Mission persistence
    # ------------------------------------------------------------------

    def save_missions(self, missions: dict[str, Mission]) -> None:
        """Serialize missions to state."""
        entries = {}
        for mid, m in missions.items():
            entries[mid] = {
                "mission_id": m.mission_id,
                "mission_title": m.mission_title,
                "mission_class": m.mission_class.value,
                "risk_tier": m.risk_tier.value,
                "domain_type": m.domain_type.value,
                "state": m.state.value,
                "worker_id": m.worker_id,
                "human_final_approval": m.human_final_approval,
                "reviewers": [
                    {
                        "id": r.id,
                        "model_family": r.model_family,
                        "method_type": r.method_type,
                        "region": r.region,
                        "organization": r.organization,
                    }
                    for r in m.reviewers
                ],
                "review_decisions": [
                    {
                        "reviewer_id": d.reviewer_id,
                        "decision": d.decision.value,
                        "notes": d.notes,
                    }
                    for d in m.review_decisions
                ],
                "evidence": [
                    {
                        "artifact_hash": e.artifact_hash,
                        "signature": e.signature,
                    }
                    for e in m.evidence
                ],
            }
        self._state["missions"] = entries
        self._save()

    def load_missions(self) -> dict[str, Mission]:
        """Deserialize missions from state."""
        missions = {}
        for mid, data in self._state.get("missions", {}).items():
            mission = Mission(
                mission_id=data["mission_id"],
                mission_title=data["mission_title"],
                mission_class=MissionClass(data["mission_class"]),
                risk_tier=RiskTier(data["risk_tier"]),
                domain_type=DomainType(data["domain_type"]),
                state=MissionState(data["state"]),
                worker_id=data.get("worker_id"),
                human_final_approval=data.get("human_final_approval", False),
                reviewers=[
                    Reviewer(**r) for r in data.get("reviewers", [])
                ],
                review_decisions=[
                    ReviewDecision(
                        reviewer_id=d["reviewer_id"],
                        decision=ReviewDecisionVerdict(d["decision"]),
                        notes=d.get("notes", ""),
                    )
                    for d in data.get("review_decisions", [])
                ],
                evidence=[
                    EvidenceRecord(**e) for e in data.get("evidence", [])
                ],
            )
            missions[mid] = mission
        return missions

    # ------------------------------------------------------------------
    # Reviewer quality assessment history
    # ------------------------------------------------------------------

    def save_reviewer_histories(
        self,
        histories: dict[str, list[ReviewerQualityAssessment]],
    ) -> None:
        """Serialize reviewer quality assessment histories to state.

        Each reviewer has a sliding window of past assessments used for
        calibration scoring. We persist enough to reconstruct on restart.
        """
        entries: dict[str, list[dict[str, Any]]] = {}
        for reviewer_id, assessments in histories.items():
            entries[reviewer_id] = [
                {
                    "reviewer_id": a.reviewer_id,
                    "mission_id": a.mission_id,
                    "alignment_score": a.alignment_score,
                    "calibration_score": a.calibration_score,
                    "derived_quality": a.derived_quality,
                    "assessment_utc": a.assessment_utc.strftime(
                        "%Y-%m-%dT%H:%M:%SZ"
                    ),
                }
                for a in assessments
            ]
        self._state["reviewer_histories"] = entries
        self._save()

    def load_reviewer_histories(
        self,
    ) -> dict[str, list[ReviewerQualityAssessment]]:
        """Deserialize reviewer quality assessment histories from state."""
        histories: dict[str, list[ReviewerQualityAssessment]] = {}
        for reviewer_id, entries in self._state.get(
            "reviewer_histories", {}
        ).items():
            assessments = []
            for data in entries:
                assessments.append(
                    ReviewerQualityAssessment(
                        reviewer_id=data["reviewer_id"],
                        mission_id=data["mission_id"],
                        alignment_score=data["alignment_score"],
                        calibration_score=data["calibration_score"],
                        derived_quality=data["derived_quality"],
                        assessment_utc=datetime.strptime(
                            data["assessment_utc"], "%Y-%m-%dT%H:%M:%SZ"
                        ).replace(tzinfo=timezone.utc),
                    )
                )
            histories[reviewer_id] = assessments
        return histories

    # ------------------------------------------------------------------
    # Epoch chain state
    # ------------------------------------------------------------------

    def save_epoch_state(
        self,
        previous_hash: str,
        committed_count: int,
    ) -> None:
        """Save epoch chain continuity state."""
        self._state["epoch"] = {
            "previous_hash": previous_hash,
            "committed_count": committed_count,
            "saved_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        self._save()

    def load_epoch_state(self) -> tuple[str, int]:
        """Load epoch chain continuity state.

        Returns (previous_hash, committed_count).
        Returns defaults if no state exists.
        """
        epoch = self._state.get("epoch", {})
        from genesis.crypto.epoch_service import GENESIS_PREVIOUS_HASH
        return (
            epoch.get("previous_hash", GENESIS_PREVIOUS_HASH),
            epoch.get("committed_count", 0),
        )
