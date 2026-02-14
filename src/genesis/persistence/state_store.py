"""State store — JSON-based persistence for Genesis runtime state.

Stores and recovers:
- Actor roster (all registered actors with trust scores)
- Mission state (all missions with their current lifecycle state)
- Reviewer quality assessment histories (sliding windows for calibration)
- Actor skill profiles (proficiency per skill)
- Protected leave records (leave requests, adjudications, trust freeze snapshots)
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
from genesis.models.domain_trust import DomainTrustScore
from genesis.models.quality import ReviewerQualityAssessment
from genesis.models.market import (
    AllocationResult,
    Bid,
    BidState,
    ListingState,
    MarketListing,
)
from genesis.models.skill import (
    ActorSkillProfile,
    SkillId,
    SkillProficiency,
    SkillRequirement,
)
from genesis.models.leave import (
    AdjudicationVerdict,
    LeaveAdjudication,
    LeaveCategory,
    LeaveRecord,
    LeaveState,
)
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
            # Serialize domain scores
            domain_scores_data: dict[str, dict[str, Any]] = {}
            for domain, ds in record.domain_scores.items():
                if isinstance(ds, DomainTrustScore):
                    domain_scores_data[domain] = {
                        "domain": ds.domain,
                        "score": ds.score,
                        "quality": ds.quality,
                        "reliability": ds.reliability,
                        "volume": ds.volume,
                        "effort": ds.effort,
                        "mission_count": ds.mission_count,
                        "last_active_utc": (
                            ds.last_active_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
                            if ds.last_active_utc
                            else None
                        ),
                    }

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
                "last_active_utc": (
                    record.last_active_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
                    if record.last_active_utc
                    else None
                ),
                "domain_scores": domain_scores_data,
            }
        self._state["trust_records"] = entries
        self._save()

    def load_trust_records(self) -> dict[str, TrustRecord]:
        """Deserialize trust records from state."""
        records = {}
        for actor_id, data in self._state.get("trust_records", {}).items():
            # Deserialize domain scores
            domain_scores: dict[str, DomainTrustScore] = {}
            for domain, ds_data in data.get("domain_scores", {}).items():
                last_active = None
                if ds_data.get("last_active_utc"):
                    last_active = datetime.strptime(
                        ds_data["last_active_utc"], "%Y-%m-%dT%H:%M:%SZ"
                    ).replace(tzinfo=timezone.utc)
                domain_scores[domain] = DomainTrustScore(
                    domain=ds_data.get("domain", domain),
                    score=ds_data.get("score", 0.0),
                    quality=ds_data.get("quality", 0.0),
                    reliability=ds_data.get("reliability", 0.0),
                    volume=ds_data.get("volume", 0.0),
                    effort=ds_data.get("effort", 0.0),
                    mission_count=ds_data.get("mission_count", 0),
                    last_active_utc=last_active,
                )

            # Deserialize last_active_utc for the global record
            last_active_utc = None
            if data.get("last_active_utc"):
                last_active_utc = datetime.strptime(
                    data["last_active_utc"], "%Y-%m-%dT%H:%M:%SZ"
                ).replace(tzinfo=timezone.utc)

            record = TrustRecord(
                actor_id=data["actor_id"],
                actor_kind=ActorKind(data["actor_kind"]),
                score=data["score"],
                quality=data.get("quality", 0.0),
                reliability=data.get("reliability", 0.0),
                volume=data.get("volume", 0.0),
                effort=data.get("effort", 0.0),
                last_active_utc=last_active_utc,
                domain_scores=domain_scores,
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
                "skill_requirements": [
                    {
                        "skill_id": req.skill_id.canonical,
                        "minimum_proficiency": req.minimum_proficiency,
                        "required": req.required,
                    }
                    for req in m.skill_requirements
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
                skill_requirements=[
                    SkillRequirement(
                        skill_id=SkillId.parse(sr["skill_id"]),
                        minimum_proficiency=sr.get("minimum_proficiency", 0.0),
                        required=sr.get("required", True),
                    )
                    for sr in data.get("skill_requirements", [])
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
    # Actor skill profiles
    # ------------------------------------------------------------------

    def save_skill_profiles(
        self,
        profiles: dict[str, ActorSkillProfile],
    ) -> None:
        """Serialize actor skill profiles to state."""
        entries: dict[str, dict[str, Any]] = {}
        for actor_id, profile in profiles.items():
            skills_data: dict[str, dict[str, Any]] = {}
            for canonical, sp in profile.skills.items():
                skills_data[canonical] = {
                    "domain": sp.skill_id.domain,
                    "skill": sp.skill_id.skill,
                    "proficiency_score": sp.proficiency_score,
                    "evidence_count": sp.evidence_count,
                    "last_demonstrated_utc": (
                        sp.last_demonstrated_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
                        if sp.last_demonstrated_utc
                        else None
                    ),
                    "endorsement_count": sp.endorsement_count,
                    "source": sp.source,
                }
            entries[actor_id] = {
                "actor_id": profile.actor_id,
                "skills": skills_data,
                "primary_domains": profile.primary_domains,
                "updated_utc": (
                    profile.updated_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
                    if profile.updated_utc
                    else None
                ),
            }
        self._state["skill_profiles"] = entries
        self._save()

    def load_skill_profiles(self) -> dict[str, ActorSkillProfile]:
        """Deserialize actor skill profiles from state."""
        profiles: dict[str, ActorSkillProfile] = {}
        for actor_id, data in self._state.get("skill_profiles", {}).items():
            skills: dict[str, SkillProficiency] = {}
            for canonical, sp_data in data.get("skills", {}).items():
                skill_id = SkillId(
                    domain=sp_data["domain"],
                    skill=sp_data["skill"],
                )
                last_demo = None
                if sp_data.get("last_demonstrated_utc"):
                    last_demo = datetime.strptime(
                        sp_data["last_demonstrated_utc"],
                        "%Y-%m-%dT%H:%M:%SZ",
                    ).replace(tzinfo=timezone.utc)

                skills[canonical] = SkillProficiency(
                    skill_id=skill_id,
                    proficiency_score=sp_data["proficiency_score"],
                    evidence_count=sp_data.get("evidence_count", 0),
                    last_demonstrated_utc=last_demo,
                    endorsement_count=sp_data.get("endorsement_count", 0),
                    source=sp_data.get("source", "outcome_derived"),
                )

            updated = None
            if data.get("updated_utc"):
                updated = datetime.strptime(
                    data["updated_utc"],
                    "%Y-%m-%dT%H:%M:%SZ",
                ).replace(tzinfo=timezone.utc)

            profiles[actor_id] = ActorSkillProfile(
                actor_id=data["actor_id"],
                skills=skills,
                primary_domains=data.get("primary_domains", []),
                updated_utc=updated,
            )
        return profiles

    # ------------------------------------------------------------------
    # Market listings persistence
    # ------------------------------------------------------------------

    def save_listings(
        self,
        listings: dict[str, MarketListing],
        bids: dict[str, list[Bid]],
    ) -> None:
        """Serialize market listings and bids to state."""
        listing_entries: dict[str, dict[str, Any]] = {}
        for lid, listing in listings.items():
            listing_entries[lid] = {
                "listing_id": listing.listing_id,
                "title": listing.title,
                "description": listing.description,
                "creator_id": listing.creator_id,
                "state": listing.state.value,
                "skill_requirements": [
                    {
                        "skill_id": req.skill_id.canonical,
                        "minimum_proficiency": req.minimum_proficiency,
                        "required": req.required,
                    }
                    for req in listing.skill_requirements
                ],
                "created_utc": (
                    listing.created_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
                    if listing.created_utc else None
                ),
                "opened_utc": (
                    listing.opened_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
                    if listing.opened_utc else None
                ),
                "allocated_utc": (
                    listing.allocated_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
                    if listing.allocated_utc else None
                ),
                "allocated_worker_id": listing.allocated_worker_id,
                "allocated_mission_id": listing.allocated_mission_id,
                "domain_tags": listing.domain_tags,
                "preferences": listing.preferences,
            }

        bid_entries: dict[str, list[dict[str, Any]]] = {}
        for lid, bid_list in bids.items():
            bid_entries[lid] = [
                {
                    "bid_id": b.bid_id,
                    "listing_id": b.listing_id,
                    "worker_id": b.worker_id,
                    "state": b.state.value,
                    "relevance_score": b.relevance_score,
                    "global_trust": b.global_trust,
                    "domain_trust": b.domain_trust,
                    "composite_score": b.composite_score,
                    "submitted_utc": (
                        b.submitted_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
                        if b.submitted_utc else None
                    ),
                    "notes": b.notes,
                }
                for b in bid_list
            ]

        self._state["listings"] = listing_entries
        self._state["bids"] = bid_entries
        self._save()

    def load_listings(self) -> tuple[dict[str, MarketListing], dict[str, list[Bid]]]:
        """Deserialize market listings and bids from state.

        Returns (listings_dict, bids_dict).
        """
        listings: dict[str, MarketListing] = {}
        for lid, data in self._state.get("listings", {}).items():
            created_utc = None
            if data.get("created_utc"):
                created_utc = datetime.strptime(
                    data["created_utc"], "%Y-%m-%dT%H:%M:%SZ"
                ).replace(tzinfo=timezone.utc)

            opened_utc = None
            if data.get("opened_utc"):
                opened_utc = datetime.strptime(
                    data["opened_utc"], "%Y-%m-%dT%H:%M:%SZ"
                ).replace(tzinfo=timezone.utc)

            allocated_utc = None
            if data.get("allocated_utc"):
                allocated_utc = datetime.strptime(
                    data["allocated_utc"], "%Y-%m-%dT%H:%M:%SZ"
                ).replace(tzinfo=timezone.utc)

            listings[lid] = MarketListing(
                listing_id=data["listing_id"],
                title=data["title"],
                description=data["description"],
                creator_id=data["creator_id"],
                state=ListingState(data["state"]),
                skill_requirements=[
                    SkillRequirement(
                        skill_id=SkillId.parse(sr["skill_id"]),
                        minimum_proficiency=sr.get("minimum_proficiency", 0.0),
                        required=sr.get("required", True),
                    )
                    for sr in data.get("skill_requirements", [])
                ],
                created_utc=created_utc,
                opened_utc=opened_utc,
                allocated_utc=allocated_utc,
                allocated_worker_id=data.get("allocated_worker_id"),
                allocated_mission_id=data.get("allocated_mission_id"),
                domain_tags=data.get("domain_tags", []),
                preferences=data.get("preferences", {}),
            )

        bids: dict[str, list[Bid]] = {}
        for lid, bid_list in self._state.get("bids", {}).items():
            bids[lid] = []
            for bd in bid_list:
                submitted_utc = None
                if bd.get("submitted_utc"):
                    submitted_utc = datetime.strptime(
                        bd["submitted_utc"], "%Y-%m-%dT%H:%M:%SZ"
                    ).replace(tzinfo=timezone.utc)

                bids[lid].append(Bid(
                    bid_id=bd["bid_id"],
                    listing_id=bd["listing_id"],
                    worker_id=bd["worker_id"],
                    state=BidState(bd["state"]),
                    relevance_score=bd.get("relevance_score", 0.0),
                    global_trust=bd.get("global_trust", 0.0),
                    domain_trust=bd.get("domain_trust", 0.0),
                    composite_score=bd.get("composite_score", 0.0),
                    submitted_utc=submitted_utc,
                    notes=bd.get("notes", ""),
                ))

        return listings, bids

    # ------------------------------------------------------------------
    # Protected leave records
    # ------------------------------------------------------------------

    def save_leave_records(
        self,
        records: dict[str, LeaveRecord],
    ) -> None:
        """Serialize protected leave records to state.

        Persists the full leave record including adjudications,
        trust freeze snapshots, and domain score snapshots.
        """
        entries: dict[str, dict[str, Any]] = {}
        for leave_id, record in records.items():
            # Serialize adjudications
            adjudications_data = []
            for adj in record.adjudications:
                adjudications_data.append({
                    "adjudicator_id": adj.adjudicator_id,
                    "verdict": adj.verdict.value,
                    "domain_qualified": adj.domain_qualified,
                    "trust_score_at_decision": adj.trust_score_at_decision,
                    "notes": adj.notes,
                    "timestamp_utc": (
                        adj.timestamp_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
                        if adj.timestamp_utc else None
                    ),
                })

            # Serialize domain scores at freeze snapshot
            domain_scores_data: dict[str, dict[str, Any]] = {}
            for domain, ds in record.domain_scores_at_freeze.items():
                if hasattr(ds, "score"):
                    # DomainTrustScore object
                    domain_scores_data[domain] = {
                        "domain": ds.domain,
                        "score": ds.score,
                        "quality": ds.quality,
                        "reliability": ds.reliability,
                        "volume": ds.volume,
                        "effort": ds.effort,
                        "mission_count": ds.mission_count,
                        "last_active_utc": (
                            ds.last_active_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
                            if ds.last_active_utc else None
                        ),
                    }

            entries[leave_id] = {
                "leave_id": record.leave_id,
                "actor_id": record.actor_id,
                "category": record.category.value,
                "state": record.state.value,
                "reason_summary": record.reason_summary,
                "petitioner_id": record.petitioner_id,
                "adjudications": adjudications_data,
                "trust_score_at_freeze": record.trust_score_at_freeze,
                "last_active_utc_at_freeze": (
                    record.last_active_utc_at_freeze.strftime("%Y-%m-%dT%H:%M:%SZ")
                    if record.last_active_utc_at_freeze else None
                ),
                "domain_scores_at_freeze": domain_scores_data,
                "pre_leave_status": record.pre_leave_status,
                "granted_duration_days": record.granted_duration_days,
                "expires_utc": (
                    record.expires_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
                    if record.expires_utc else None
                ),
                "requested_utc": (
                    record.requested_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
                    if record.requested_utc else None
                ),
                "approved_utc": (
                    record.approved_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
                    if record.approved_utc else None
                ),
                "denied_utc": (
                    record.denied_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
                    if record.denied_utc else None
                ),
                "returned_utc": (
                    record.returned_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
                    if record.returned_utc else None
                ),
                "memorialised_utc": (
                    record.memorialised_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
                    if record.memorialised_utc else None
                ),
            }
        self._state["leave_records"] = entries
        self._save()

    def load_leave_records(self) -> dict[str, LeaveRecord]:
        """Deserialize protected leave records from state.

        Reconstructs the full leave record including adjudications
        and trust freeze domain score snapshots.
        """
        records: dict[str, LeaveRecord] = {}
        for leave_id, data in self._state.get("leave_records", {}).items():
            # Deserialize adjudications
            adjudications: list[LeaveAdjudication] = []
            for adj_data in data.get("adjudications", []):
                adj_ts = None
                if adj_data.get("timestamp_utc"):
                    adj_ts = datetime.strptime(
                        adj_data["timestamp_utc"], "%Y-%m-%dT%H:%M:%SZ"
                    ).replace(tzinfo=timezone.utc)
                adjudications.append(LeaveAdjudication(
                    adjudicator_id=adj_data["adjudicator_id"],
                    verdict=AdjudicationVerdict(adj_data["verdict"]),
                    domain_qualified=adj_data["domain_qualified"],
                    trust_score_at_decision=adj_data["trust_score_at_decision"],
                    notes=adj_data.get("notes", ""),
                    timestamp_utc=adj_ts,
                ))

            # Deserialize domain scores at freeze
            domain_scores_at_freeze: dict[str, DomainTrustScore] = {}
            for domain, ds_data in data.get("domain_scores_at_freeze", {}).items():
                last_active = None
                if ds_data.get("last_active_utc"):
                    last_active = datetime.strptime(
                        ds_data["last_active_utc"], "%Y-%m-%dT%H:%M:%SZ"
                    ).replace(tzinfo=timezone.utc)
                domain_scores_at_freeze[domain] = DomainTrustScore(
                    domain=ds_data.get("domain", domain),
                    score=ds_data.get("score", 0.0),
                    quality=ds_data.get("quality", 0.0),
                    reliability=ds_data.get("reliability", 0.0),
                    volume=ds_data.get("volume", 0.0),
                    effort=ds_data.get("effort", 0.0),
                    mission_count=ds_data.get("mission_count", 0),
                    last_active_utc=last_active,
                )

            # Deserialize timestamps
            last_active_at_freeze = None
            if data.get("last_active_utc_at_freeze"):
                last_active_at_freeze = datetime.strptime(
                    data["last_active_utc_at_freeze"], "%Y-%m-%dT%H:%M:%SZ"
                ).replace(tzinfo=timezone.utc)

            expires_utc = None
            if data.get("expires_utc"):
                expires_utc = datetime.strptime(
                    data["expires_utc"], "%Y-%m-%dT%H:%M:%SZ"
                ).replace(tzinfo=timezone.utc)

            requested_utc = None
            if data.get("requested_utc"):
                requested_utc = datetime.strptime(
                    data["requested_utc"], "%Y-%m-%dT%H:%M:%SZ"
                ).replace(tzinfo=timezone.utc)

            approved_utc = None
            if data.get("approved_utc"):
                approved_utc = datetime.strptime(
                    data["approved_utc"], "%Y-%m-%dT%H:%M:%SZ"
                ).replace(tzinfo=timezone.utc)

            denied_utc = None
            if data.get("denied_utc"):
                denied_utc = datetime.strptime(
                    data["denied_utc"], "%Y-%m-%dT%H:%M:%SZ"
                ).replace(tzinfo=timezone.utc)

            returned_utc = None
            if data.get("returned_utc"):
                returned_utc = datetime.strptime(
                    data["returned_utc"], "%Y-%m-%dT%H:%M:%SZ"
                ).replace(tzinfo=timezone.utc)

            memorialised_utc = None
            if data.get("memorialised_utc"):
                memorialised_utc = datetime.strptime(
                    data["memorialised_utc"], "%Y-%m-%dT%H:%M:%SZ"
                ).replace(tzinfo=timezone.utc)

            # Legacy compat: map "permanent" → "memorialised"
            raw_state = data["state"]
            if raw_state == "permanent":
                raw_state = "memorialised"

            records[leave_id] = LeaveRecord(
                leave_id=data["leave_id"],
                actor_id=data["actor_id"],
                category=LeaveCategory(data["category"]),
                state=LeaveState(raw_state),
                reason_summary=data.get("reason_summary", ""),
                petitioner_id=data.get("petitioner_id"),
                adjudications=adjudications,
                trust_score_at_freeze=data.get("trust_score_at_freeze"),
                last_active_utc_at_freeze=last_active_at_freeze,
                domain_scores_at_freeze=domain_scores_at_freeze,
                pre_leave_status=data.get("pre_leave_status"),
                granted_duration_days=data.get("granted_duration_days"),
                expires_utc=expires_utc,
                requested_utc=requested_utc,
                approved_utc=approved_utc,
                denied_utc=denied_utc,
                returned_utc=returned_utc,
                memorialised_utc=memorialised_utc,
            )
        return records

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
