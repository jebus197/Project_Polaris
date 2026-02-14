"""Genesis service — unified facade for the governance engine.

This is the primary interface for programmatic access to Genesis.
It orchestrates all subsystems:
- Mission lifecycle (create, submit, assign, review, approve)
- Quality assessment (derives quality from mission outcomes)
- Trust management (score computation, updates)
- Reviewer selection (constrained-random from roster)
- Epoch management (open, collect, close, anchor)
- Phase governance (G0→G1→G2→G3 progression)
- Persistence (event log, state store)

All operations produce typed results. All state changes are logged
to the event collector for eventual commitment. Audit-trail events
are never silently dropped — if no epoch is open, the operation fails
closed rather than proceeding without an audit record.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from genesis.crypto.epoch_service import EpochService, GENESIS_PREVIOUS_HASH
from genesis.engine.reviewer_router import ReviewerRouter
from genesis.engine.state_machine import MissionStateMachine
from genesis.engine.evidence import EvidenceValidator
from genesis.governance.genesis_controller import GenesisPhaseController, PhaseState
from genesis.models.commitment import CommitmentRecord, CommitmentTier
from genesis.models.governance import GenesisPhase
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
from genesis.models.quality import (
    MissionQualityReport,
    ReviewerQualityAssessment,
)
from genesis.models.skill import (
    ActorSkillProfile,
    SkillId,
    SkillProficiency,
    SkillRequirement,
)
from genesis.models.domain_trust import DomainTrustScore, TrustStatus
from genesis.models.leave import (
    AdjudicationVerdict,
    LeaveAdjudication,
    LeaveCategory,
    LeaveRecord,
    LeaveState,
)
from genesis.models.market import (
    AllocationResult,
    Bid,
    BidState,
    ListingState,
    MarketListing,
)
from genesis.models.trust import ActorKind, TrustDelta, TrustRecord
from genesis.leave.engine import LeaveAdjudicationEngine
from genesis.market.allocator import AllocationEngine
from genesis.market.listing_state_machine import ListingStateMachine
from genesis.skills.decay import SkillDecayEngine
from genesis.skills.endorsement import EndorsementEngine
from genesis.skills.matching import SkillMatchEngine
from genesis.skills.outcome_updater import SkillOutcomeUpdater
from genesis.skills.worker_matcher import WorkerMatcher
from genesis.persistence.event_log import EventLog, EventRecord, EventKind
from genesis.persistence.state_store import StateStore
from genesis.policy.resolver import PolicyResolver
from genesis.quality.engine import QualityEngine
from genesis.review.roster import ActorRoster, ActorStatus, RosterEntry
from genesis.review.selector import ReviewerSelector, SelectionResult
from genesis.skills.taxonomy import SkillTaxonomy
from genesis.trust.engine import TrustEngine


@dataclass(frozen=True)
class ServiceResult:
    """Result of a service operation."""
    success: bool
    errors: list[str] = field(default_factory=list)
    data: dict[str, Any] = field(default_factory=dict)


class GenesisService:
    """Unified governance engine facade.

    Usage:
        resolver = PolicyResolver.from_config_dir(config_dir)
        service = GenesisService(resolver)

        # Register actors
        service.register_actor(...)

        # Create and process missions
        result = service.create_mission(...)
        result = service.submit_mission(mission_id)
        result = service.assign_reviewers(mission_id, seed="beacon:...")
        result = service.submit_review(mission_id, reviewer_id, "APPROVE")
        result = service.complete_review(mission_id)
        result = service.approve_mission(mission_id)

        # Epoch lifecycle
        service.open_epoch()
        # ... operations happen, events are collected ...
        record = service.close_epoch(beacon_round=12345)

    Persistence (optional):
        service = GenesisService(resolver, event_log=log, state_store=store)
        # State is persisted on each mutation and loaded on construction.
    """

    def __init__(
        self,
        resolver: PolicyResolver,
        previous_hash: str = GENESIS_PREVIOUS_HASH,
        event_log: Optional[EventLog] = None,
        state_store: Optional[StateStore] = None,
    ) -> None:
        self._resolver = resolver
        self._trust_engine = TrustEngine(resolver)
        self._quality_engine = QualityEngine(resolver)
        self._state_machine = MissionStateMachine(resolver)
        self._reviewer_router = ReviewerRouter(resolver)
        self._evidence_validator = EvidenceValidator()
        self._phase_controller = GenesisPhaseController(resolver)

        # Skill taxonomy (optional — pre-labour-market mode if absent)
        self._taxonomy: Optional[SkillTaxonomy] = None
        if resolver.has_skill_taxonomy():
            self._taxonomy = SkillTaxonomy(resolver.skill_taxonomy_data())

        # Persistence layer (optional — in-memory if not provided)
        self._event_log = event_log
        self._state_store = state_store

        # Market layer
        self._allocation_engine = AllocationEngine(resolver)
        self._listing_sm = ListingStateMachine()
        self._match_engine = SkillMatchEngine(resolver)

        # Skill lifecycle engines
        self._skill_decay_engine = SkillDecayEngine(resolver)
        self._endorsement_engine = EndorsementEngine(resolver)
        self._skill_outcome_updater = SkillOutcomeUpdater(resolver)

        # Protected leave engine
        self._leave_engine = LeaveAdjudicationEngine(resolver)

        # Load persisted state or start fresh
        if state_store is not None:
            self._roster = state_store.load_roster()
            self._trust_records = state_store.load_trust_records()
            self._missions = state_store.load_missions()
            self._reviewer_assessment_history = state_store.load_reviewer_histories()
            self._skill_profiles = state_store.load_skill_profiles()
            self._listings, self._bids = state_store.load_listings()
            self._leave_records = state_store.load_leave_records()
            stored_hash, _ = state_store.load_epoch_state()
            self._epoch_service = EpochService(resolver, stored_hash)
        else:
            self._roster = ActorRoster()
            self._trust_records: dict[str, TrustRecord] = {}
            self._missions: dict[str, Mission] = {}
            self._reviewer_assessment_history: dict[str, list[ReviewerQualityAssessment]] = {}
            self._skill_profiles: dict[str, ActorSkillProfile] = {}
            self._listings: dict[str, MarketListing] = {}
            self._bids: dict[str, list[Bid]] = {}
            self._leave_records: dict[str, LeaveRecord] = {}
            self._epoch_service = EpochService(resolver, previous_hash)

        self._selector = ReviewerSelector(
            resolver, self._roster,
            skill_profiles=self._skill_profiles,
            trust_records=self._trust_records,
        )
        # Initialize counter from persisted log to avoid ID collision on restart
        self._event_counter = event_log.count if event_log is not None else 0
        # Leave ID counter: initialise from persisted records
        self._leave_counter = len(self._leave_records)

        # Persistence health flag: set to True if a StateStore write fails
        # after an audit event has been durably committed. In-memory state
        # remains correct (aligned with audit trail), but the StateStore is
        # stale and needs operator intervention or event-log replay.
        self._persistence_degraded: bool = False

    # ------------------------------------------------------------------
    # Actor management
    # ------------------------------------------------------------------

    def register_actor(
        self,
        actor_id: str,
        actor_kind: ActorKind,
        region: str,
        organization: str,
        model_family: str = "human_reviewer",
        method_type: str = "human_reviewer",
        initial_trust: float = 0.10,
    ) -> ServiceResult:
        """Register a new actor in the roster."""
        try:
            entry = RosterEntry(
                actor_id=actor_id,
                actor_kind=actor_kind,
                trust_score=initial_trust,
                region=region,
                organization=organization,
                model_family=model_family,
                method_type=method_type,
            )
            self._roster.register(entry)

            aid = actor_id.strip()
            self._trust_records[aid] = TrustRecord(
                actor_id=aid,
                actor_kind=actor_kind,
                score=initial_trust,
            )

            def _rollback() -> None:
                self._roster._actors.pop(aid, None)
                self._trust_records.pop(aid, None)

            err = self._safe_persist(on_rollback=_rollback)
            if err:
                return ServiceResult(success=False, errors=[err])
            return ServiceResult(success=True, data={"actor_id": aid})
        except ValueError as e:
            return ServiceResult(success=False, errors=[str(e)])

    def get_actor(self, actor_id: str) -> Optional[RosterEntry]:
        """Look up an actor."""
        return self._roster.get(actor_id)

    def quarantine_actor(self, actor_id: str) -> ServiceResult:
        """Place an actor in quarantine."""
        entry = self._roster.get(actor_id)
        if entry is None:
            return ServiceResult(success=False, errors=[f"Actor not found: {actor_id}"])
        prev_status = entry.status
        entry.status = ActorStatus.QUARANTINED
        trust = self._trust_records.get(actor_id.strip())
        prev_quarantined = trust.quarantined if trust else None
        if trust:
            trust.quarantined = True

        def _rollback() -> None:
            entry.status = prev_status
            if trust and prev_quarantined is not None:
                trust.quarantined = prev_quarantined

        err = self._safe_persist(on_rollback=_rollback)
        if err:
            return ServiceResult(success=False, errors=[err])
        return ServiceResult(success=True)

    # ------------------------------------------------------------------
    # Skill profile management
    # ------------------------------------------------------------------

    def update_actor_skills(
        self,
        actor_id: str,
        skills: list[SkillProficiency],
    ) -> ServiceResult:
        """Update an actor's skill profile.

        Validates each skill against the taxonomy (if loaded).
        Creates the profile if it doesn't exist; merges otherwise.
        """
        actor = self._roster.get(actor_id)
        if actor is None:
            return ServiceResult(
                success=False,
                errors=[f"Actor not found: {actor_id}"],
            )

        # Validate skills against taxonomy
        if self._taxonomy is not None:
            errors: list[str] = []
            for sp in skills:
                skill_errors = self._taxonomy.validate_skill_id(sp.skill_id)
                errors.extend(skill_errors)
            if errors:
                return ServiceResult(success=False, errors=errors)

        # Snapshot pre-state for rollback
        old_profile = self._skill_profiles.get(actor_id)
        old_roster_profile = actor.skill_profile
        # Deep copy: snapshot old skill keys+values if profile existed
        old_skills = dict(old_profile.skills) if old_profile else None
        old_domains = list(old_profile.primary_domains) if old_profile else None
        old_updated = old_profile.updated_utc if old_profile else None

        # Get or create profile
        profile = self._skill_profiles.get(actor_id)
        if profile is None:
            profile = ActorSkillProfile(actor_id=actor_id)
            self._skill_profiles[actor_id] = profile

        # Merge skills
        for sp in skills:
            profile.skills[sp.skill_id.canonical] = sp

        profile.recompute_primary_domains()
        profile.updated_utc = datetime.now(timezone.utc)

        # Attach to roster entry for future matching
        actor.skill_profile = profile

        def _rollback() -> None:
            if old_profile is None:
                self._skill_profiles.pop(actor_id, None)
            else:
                old_profile.skills = old_skills  # type: ignore[assignment]
                old_profile.primary_domains = old_domains  # type: ignore[assignment]
                old_profile.updated_utc = old_updated
            actor.skill_profile = old_roster_profile

        err = self._safe_persist(on_rollback=_rollback)
        if err:
            return ServiceResult(success=False, errors=[err])
        return ServiceResult(
            success=True,
            data={
                "actor_id": actor_id,
                "skill_count": len(profile.skills),
                "primary_domains": profile.primary_domains,
            },
        )

    def get_actor_skills(self, actor_id: str) -> Optional[ActorSkillProfile]:
        """Retrieve an actor's skill profile."""
        return self._skill_profiles.get(actor_id)

    def set_mission_skill_requirements(
        self,
        mission_id: str,
        requirements: list[SkillRequirement],
    ) -> ServiceResult:
        """Set skill requirements on a mission.

        Requirements are validated against the taxonomy (if loaded).
        Can only be set on missions in DRAFT state.
        """
        mission = self._missions.get(mission_id)
        if mission is None:
            return ServiceResult(
                success=False,
                errors=[f"Mission not found: {mission_id}"],
            )

        if mission.state != MissionState.DRAFT:
            return ServiceResult(
                success=False,
                errors=[
                    f"Skill requirements can only be set on DRAFT missions, "
                    f"got {mission.state.value}"
                ],
            )

        # Validate against taxonomy
        if self._taxonomy is not None:
            errors = self._taxonomy.validate_requirements(requirements)
            if errors:
                return ServiceResult(success=False, errors=errors)

        prev_reqs = mission.skill_requirements
        mission.skill_requirements = list(requirements)

        def _rollback() -> None:
            mission.skill_requirements = prev_reqs

        err = self._safe_persist(on_rollback=_rollback)
        if err:
            return ServiceResult(success=False, errors=[err])
        return ServiceResult(
            success=True,
            data={
                "mission_id": mission_id,
                "requirement_count": len(requirements),
            },
        )

    def find_matching_workers(
        self,
        requirements: list[SkillRequirement],
        exclude_ids: set[str] | None = None,
        min_trust: float = 0.0,
        limit: int = 10,
    ) -> ServiceResult:
        """Find workers matching the given skill requirements.

        Returns ranked list of matching workers sorted by composite
        score (relevance * 0.50 + global_trust * 0.20 + domain_trust * 0.30).
        """
        matcher = WorkerMatcher(
            self._resolver,
            self._roster,
            self._trust_records,
            self._skill_profiles,
        )
        matches = matcher.find_matches(
            requirements=requirements,
            exclude_ids=exclude_ids,
            min_trust=min_trust,
            limit=limit,
        )
        return ServiceResult(
            success=True,
            data={
                "matches": [
                    {
                        "actor_id": m.actor_id,
                        "relevance_score": m.relevance_score,
                        "global_trust": m.global_trust,
                        "domain_trust": m.domain_trust,
                        "composite_score": m.composite_score,
                    }
                    for m in matches
                ],
                "total_matches": len(matches),
            },
        )

    # ------------------------------------------------------------------
    # Skill lifecycle — decay, endorsement, outcome updates
    # ------------------------------------------------------------------

    def endorse_skill(
        self,
        endorser_id: str,
        target_id: str,
        skill_id: SkillId,
    ) -> ServiceResult:
        """Endorse a peer's skill.

        Rules:
        - Self-endorsement blocked.
        - Endorser must have the skill at sufficient proficiency.
        - Target must already have the skill (outcome-derived).
        - Diminishing returns on repeated endorsements.
        """
        endorser_profile = self._skill_profiles.get(endorser_id)
        if endorser_profile is None:
            return ServiceResult(
                success=False,
                errors=[f"Endorser has no skill profile: {endorser_id}"],
            )

        endorser_trust = self._trust_records.get(endorser_id)
        if endorser_trust is None:
            return ServiceResult(
                success=False,
                errors=[f"No trust record for endorser: {endorser_id}"],
            )

        target_profile = self._skill_profiles.get(target_id)
        if target_profile is None:
            return ServiceResult(
                success=False,
                errors=[f"Target has no skill profile: {target_id}"],
            )

        # Snapshot target skill for rollback
        old_sp = target_profile.skills.get(skill_id.canonical)

        result = self._endorsement_engine.endorse(
            endorser_id=endorser_id,
            endorser_profile=endorser_profile,
            endorser_trust=endorser_trust,
            target_profile=target_profile,
            skill_id=skill_id,
        )

        if not result.success:
            return ServiceResult(success=False, errors=result.errors)

        def _rollback() -> None:
            if old_sp is not None:
                target_profile.skills[skill_id.canonical] = old_sp
            else:
                target_profile.skills.pop(skill_id.canonical, None)

        err = self._safe_persist(on_rollback=_rollback)
        if err:
            return ServiceResult(success=False, errors=[err])
        return ServiceResult(
            success=True,
            data={
                "endorser_id": endorser_id,
                "target_id": target_id,
                "skill": skill_id.canonical,
                "old_proficiency": result.old_proficiency,
                "new_proficiency": result.new_proficiency,
                "boost_applied": result.boost_applied,
            },
        )

    def run_skill_decay(
        self,
        actor_id: str | None = None,
    ) -> ServiceResult:
        """Apply skill decay to one actor or all actors.

        Should be called periodically (e.g. daily). Decays skill
        proficiencies that haven't been demonstrated recently.
        Skills below the prune threshold are removed.

        Args:
            actor_id: If specified, only decay this actor. If None, all.
        """
        if actor_id is not None:
            profiles_to_decay = {actor_id: self._skill_profiles.get(actor_id)}
            if profiles_to_decay[actor_id] is None:
                return ServiceResult(
                    success=False,
                    errors=[f"No skill profile for actor: {actor_id}"],
                )
        else:
            profiles_to_decay = dict(self._skill_profiles)

        results: list[dict[str, Any]] = []
        total_decayed = 0
        total_pruned = 0
        # Snapshot for rollback: {actor_id: (old_profile, old_roster_profile)}
        snapshots: dict[str, tuple[Any, Any]] = {}

        for aid, profile in profiles_to_decay.items():
            if profile is None:
                continue
            # Skip actors on protected leave — skill decay is frozen
            if self.is_actor_on_leave(aid):
                continue
            is_machine = False
            trust_rec = self._trust_records.get(aid)
            if trust_rec:
                is_machine = trust_rec.actor_kind == ActorKind.MACHINE

            new_profile, decay_result = self._skill_decay_engine.apply_decay(
                profile, is_machine=is_machine,
            )

            if decay_result.decayed_count > 0 or decay_result.pruned_count > 0:
                roster_entry = self._roster.get(aid)
                snapshots[aid] = (profile, roster_entry.skill_profile if roster_entry else None)
                self._skill_profiles[aid] = new_profile
                # Update roster entry skill profile
                if roster_entry:
                    roster_entry.skill_profile = new_profile

                total_decayed += decay_result.decayed_count
                total_pruned += decay_result.pruned_count
                results.append({
                    "actor_id": aid,
                    "decayed": decay_result.decayed_count,
                    "pruned": decay_result.pruned_count,
                    "skills_remaining": decay_result.skills_after,
                })

        if results:
            def _rollback() -> None:
                for s_aid, (old_prof, old_roster_prof) in snapshots.items():
                    self._skill_profiles[s_aid] = old_prof
                    r_entry = self._roster.get(s_aid)
                    if r_entry:
                        r_entry.skill_profile = old_roster_prof

            err = self._safe_persist(on_rollback=_rollback)
            if err:
                return ServiceResult(success=False, errors=[err])

        return ServiceResult(
            success=True,
            data={
                "actors_affected": len(results),
                "total_decayed": total_decayed,
                "total_pruned": total_pruned,
                "details": results,
            },
        )

    def _update_skills_from_outcome(
        self,
        worker_id: str,
        mission: Mission,
        approved: bool,
    ) -> Optional[dict[str, Any]]:
        """Internal: update worker skills after mission completion.

        Called by _assess_and_update_quality when a mission reaches
        a terminal state with skill requirements.
        """
        if not mission.skill_requirements:
            return None

        profile = self._skill_profiles.get(worker_id)
        if profile is None:
            # Create a new profile for the worker
            profile = ActorSkillProfile(actor_id=worker_id)
            self._skill_profiles[worker_id] = profile

        result = self._skill_outcome_updater.update_from_outcome(
            profile, mission, approved,
        )

        if result.skills_updated > 0:
            # Update roster entry
            roster_entry = self._roster.get(worker_id)
            if roster_entry:
                roster_entry.skill_profile = profile

        return {
            "skills_updated": result.skills_updated,
            "updates": [
                {
                    "skill": u.skill_id,
                    "old": u.old_proficiency,
                    "new": u.new_proficiency,
                    "delta": u.delta,
                }
                for u in result.updates
            ],
        }

    # ------------------------------------------------------------------
    # Labour market — listings and bids
    # ------------------------------------------------------------------

    def create_listing(
        self,
        listing_id: str,
        title: str,
        description: str,
        creator_id: str,
        skill_requirements: list[SkillRequirement] | None = None,
        domain_tags: list[str] | None = None,
        preferences: dict[str, Any] | None = None,
    ) -> ServiceResult:
        """Create a new market listing in DRAFT state."""
        if listing_id in self._listings:
            return ServiceResult(
                success=False,
                errors=[f"Listing already exists: {listing_id}"],
            )

        # Verify creator is registered
        creator = self._roster.get(creator_id)
        if creator is None:
            return ServiceResult(
                success=False,
                errors=[f"Creator not found: {creator_id}"],
            )

        # Validate skill requirements against taxonomy
        reqs = skill_requirements or []
        if self._taxonomy is not None and reqs:
            errors = self._taxonomy.validate_requirements(reqs)
            if errors:
                return ServiceResult(success=False, errors=errors)

        listing = MarketListing(
            listing_id=listing_id,
            title=title,
            description=description,
            creator_id=creator_id,
            state=ListingState.DRAFT,
            skill_requirements=reqs,
            created_utc=datetime.now(timezone.utc),
            domain_tags=domain_tags or [],
            preferences=preferences or {},
        )
        self._listings[listing_id] = listing
        self._bids[listing_id] = []

        # Record audit event
        err = self._record_listing_event(listing, "created")
        if err:
            del self._listings[listing_id]
            del self._bids[listing_id]
            return ServiceResult(success=False, errors=[err])

        warning = self._safe_persist_post_audit()
        data: dict[str, Any] = {
            "listing_id": listing_id,
            "state": listing.state.value,
        }
        if warning:
            data["warning"] = warning
        return ServiceResult(success=True, data=data)

    def open_listing(self, listing_id: str) -> ServiceResult:
        """Transition listing from DRAFT → OPEN."""
        return self._transition_listing(listing_id, ListingState.OPEN)

    def start_accepting_bids(self, listing_id: str) -> ServiceResult:
        """Transition listing from OPEN → ACCEPTING_BIDS."""
        return self._transition_listing(listing_id, ListingState.ACCEPTING_BIDS)

    def submit_bid(
        self,
        bid_id: str,
        listing_id: str,
        worker_id: str,
        notes: str = "",
    ) -> ServiceResult:
        """Submit a bid on a listing.

        Auto-computes relevance and trust scores for the worker.
        Validates bid eligibility (trust threshold, duplicate check).
        """
        listing = self._listings.get(listing_id)
        if listing is None:
            return ServiceResult(
                success=False,
                errors=[f"Listing not found: {listing_id}"],
            )

        if listing.state not in (ListingState.OPEN, ListingState.ACCEPTING_BIDS):
            return ServiceResult(
                success=False,
                errors=[
                    f"Listing {listing_id} is not accepting bids "
                    f"(state: {listing.state.value})"
                ],
            )

        # Verify worker exists and is available
        worker = self._roster.get(worker_id)
        if worker is None:
            return ServiceResult(
                success=False,
                errors=[f"Worker not found: {worker_id}"],
            )
        if not worker.is_available():
            return ServiceResult(
                success=False,
                errors=[f"Worker {worker_id} is not available (status: {worker.status.value})"],
            )

        # Check bid requirements
        bid_reqs = self._resolver.market_bid_requirements()
        min_trust = bid_reqs.get("min_trust_to_bid", 0.10)
        trust_record = self._trust_records.get(worker_id)
        global_trust = trust_record.score if trust_record else 0.0
        if global_trust < min_trust:
            return ServiceResult(
                success=False,
                errors=[
                    f"Worker trust {global_trust:.2f} below minimum "
                    f"{min_trust:.2f} to bid"
                ],
            )

        # Check duplicate bids
        if not bid_reqs.get("allow_multiple_bids_per_worker", False):
            existing_bids = self._bids.get(listing_id, [])
            for b in existing_bids:
                if b.worker_id == worker_id and b.state == BidState.SUBMITTED:
                    return ServiceResult(
                        success=False,
                        errors=[f"Worker {worker_id} already has a bid on listing {listing_id}"],
                    )

        # Check max bids
        listing_defaults = self._resolver.market_listing_defaults()
        max_bids = listing_defaults.get("max_bids_per_listing", 50)
        active_bids = [
            b for b in self._bids.get(listing_id, [])
            if b.state == BidState.SUBMITTED
        ]
        if len(active_bids) >= max_bids:
            return ServiceResult(
                success=False,
                errors=[f"Listing {listing_id} has reached maximum bids ({max_bids})"],
            )

        # Compute relevance score
        profile = self._skill_profiles.get(worker_id)
        relevance = self._match_engine.compute_relevance(
            profile, listing.skill_requirements, trust_record,
        )

        # Compute domain trust
        domain_trust = 0.0
        if trust_record and listing.skill_requirements:
            domains = {r.skill_id.domain for r in listing.skill_requirements}
            domain_scores = [
                trust_record.domain_scores[d].score
                for d in domains
                if d in trust_record.domain_scores
            ]
            if domain_scores:
                domain_trust = sum(domain_scores) / len(domains)

        # Compute composite score
        w_rel, w_global, w_domain = self._allocation_engine._allocation_weights()
        composite = (
            w_rel * relevance
            + w_global * global_trust
            + w_domain * domain_trust
        )

        bid = Bid(
            bid_id=bid_id,
            listing_id=listing_id,
            worker_id=worker_id,
            state=BidState.SUBMITTED,
            relevance_score=relevance,
            global_trust=global_trust,
            domain_trust=domain_trust,
            composite_score=composite,
            submitted_utc=datetime.now(timezone.utc),
            notes=notes,
        )
        self._bids.setdefault(listing_id, []).append(bid)

        # Record bid event
        err = self._record_bid_event(bid)
        if err:
            self._bids[listing_id].pop()
            return ServiceResult(success=False, errors=[err])

        warning = self._safe_persist_post_audit()
        data: dict[str, Any] = {
            "bid_id": bid_id,
            "listing_id": listing_id,
            "worker_id": worker_id,
            "relevance_score": relevance,
            "global_trust": global_trust,
            "domain_trust": domain_trust,
            "composite_score": composite,
        }
        if warning:
            data["warning"] = warning
        return ServiceResult(success=True, data=data)

    def withdraw_bid(self, bid_id: str, listing_id: str) -> ServiceResult:
        """Withdraw a previously submitted bid."""
        listing = self._listings.get(listing_id)
        if listing is None:
            return ServiceResult(
                success=False,
                errors=[f"Listing not found: {listing_id}"],
            )

        bids = self._bids.get(listing_id, [])
        for bid in bids:
            if bid.bid_id == bid_id:
                if bid.state != BidState.SUBMITTED:
                    return ServiceResult(
                        success=False,
                        errors=[f"Bid {bid_id} cannot be withdrawn (state: {bid.state.value})"],
                    )
                prev_state = bid.state
                bid.state = BidState.WITHDRAWN

                def _rollback() -> None:
                    bid.state = prev_state

                err = self._safe_persist(on_rollback=_rollback)
                if err:
                    return ServiceResult(success=False, errors=[err])
                return ServiceResult(
                    success=True,
                    data={"bid_id": bid_id, "state": bid.state.value},
                )

        return ServiceResult(
            success=False,
            errors=[f"Bid not found: {bid_id}"],
        )

    def evaluate_and_allocate(
        self,
        listing_id: str,
        mission_class: MissionClass = MissionClass.DOCUMENTATION_UPDATE,
        domain_type: DomainType = DomainType.OBJECTIVE,
    ) -> ServiceResult:
        """Close bidding, evaluate bids, allocate worker, create mission.

        Full flow:
        1. Transition listing to EVALUATING
        2. Score and rank all bids
        3. Select best bid → ALLOCATED
        4. Auto-create mission from listing
        5. Optionally close listing
        """
        listing = self._listings.get(listing_id)
        if listing is None:
            return ServiceResult(
                success=False,
                errors=[f"Listing not found: {listing_id}"],
            )

        # Snapshot listing state before any mutation (for rollback)
        initial_listing_state = listing.state

        # Transition to EVALUATING (validates current state)
        if listing.state == ListingState.ACCEPTING_BIDS:
            errors = ListingStateMachine.apply_transition(listing, ListingState.EVALUATING)
            if errors:
                return ServiceResult(success=False, errors=errors)
        elif listing.state != ListingState.EVALUATING:
            return ServiceResult(
                success=False,
                errors=[
                    f"Cannot evaluate listing in state {listing.state.value}. "
                    f"Expected ACCEPTING_BIDS or EVALUATING."
                ],
            )

        bids = self._bids.get(listing_id, [])
        submitted_bids = [b for b in bids if b.state == BidState.SUBMITTED]

        if not submitted_bids:
            # Rollback EVALUATING transition
            listing.state = initial_listing_state
            return ServiceResult(
                success=False,
                errors=[f"No submitted bids for listing {listing_id}"],
            )

        # Evaluate and allocate
        result = self._allocation_engine.evaluate_and_allocate(listing, submitted_bids)
        if result is None:
            listing.state = initial_listing_state
            return ServiceResult(
                success=False,
                errors=["Allocation failed — no valid bids after scoring"],
            )

        # Snapshot bid states for rollback
        prior_bid_states = {bid.bid_id: bid.state for bid in bids}

        # Update bid states
        for bid in bids:
            if bid.bid_id == result.selected_bid_id:
                bid.state = BidState.ACCEPTED
            elif bid.state == BidState.SUBMITTED:
                bid.state = BidState.REJECTED

        # Snapshot listing fields for rollback
        prior_allocated_worker_id = listing.allocated_worker_id
        prior_allocated_utc = listing.allocated_utc
        prior_allocated_mission_id = listing.allocated_mission_id

        # Transition listing to ALLOCATED
        errors = ListingStateMachine.apply_transition(listing, ListingState.ALLOCATED)
        if errors:
            # Rollback bid states and EVALUATING transition
            listing.state = initial_listing_state
            for bid in bids:
                if bid.bid_id in prior_bid_states:
                    bid.state = prior_bid_states[bid.bid_id]
            return ServiceResult(success=False, errors=errors)

        listing.allocated_worker_id = result.selected_worker_id
        listing.allocated_utc = datetime.now(timezone.utc)

        def _rollback_allocation() -> None:
            """Rollback all allocation mutations to initial state."""
            listing.state = initial_listing_state
            listing.allocated_worker_id = prior_allocated_worker_id
            listing.allocated_utc = prior_allocated_utc
            listing.allocated_mission_id = prior_allocated_mission_id
            for bid in bids:
                if bid.bid_id in prior_bid_states:
                    bid.state = prior_bid_states[bid.bid_id]

        # --- Internal mission staging (no side effects until commit) ---
        # Do NOT call public create_mission() — it is a committed
        # operation with its own audit event + persist. Using it here
        # creates phantom mission events if the allocation audit fails.
        # Instead: validate, construct, audit-commit, then insert.
        mission_id = f"mission-from-{listing_id}"

        # Step 1: Validate — mission ID must be unique
        if mission_id in self._missions:
            _rollback_allocation()
            return ServiceResult(
                success=False,
                errors=[f"Allocation failed: mission already exists: {mission_id}"],
            )

        # Step 2: Construct mission object (pure — no side effects)
        tier = self._resolver.resolve_tier(mission_class)
        staged_mission = Mission(
            mission_id=mission_id,
            mission_title=listing.title,
            mission_class=mission_class,
            risk_tier=tier,
            domain_type=domain_type,
            worker_id=result.selected_worker_id,
            created_utc=datetime.now(timezone.utc),
        )
        if listing.skill_requirements:
            staged_mission.skill_requirements = list(listing.skill_requirements)

        listing.allocated_mission_id = mission_id

        # Step 3: Record allocation audit event — the single durable
        # commit point for the entire transaction. The allocation event
        # payload contains listing_id, worker_id, and mission_id, serving
        # as the audit record for both allocation and mission creation.
        # If this fails, nothing has been written — clean rollback.
        err = self._record_allocation_event(listing, result)
        if err:
            _rollback_allocation()
            return ServiceResult(success=False, errors=[err])

        # Step 4: Commit — insert staged mission into memory. The
        # allocation audit event is already durable, so this is safe.
        self._missions[mission_id] = staged_mission

        # Auto-close if configured
        pre_close_state = listing.state
        defaults = self._resolver.market_listing_defaults()
        if defaults.get("auto_close_on_allocation", True):
            ListingStateMachine.apply_transition(listing, ListingState.CLOSED)

        # Audit event committed — do NOT rollback in-memory state
        persist_warning = self._safe_persist_post_audit()
        result_data: dict[str, Any] = {
            "listing_id": listing_id,
            "selected_bid_id": result.selected_bid_id,
            "selected_worker_id": result.selected_worker_id,
            "composite_score": result.composite_score,
            "runner_up_count": len(result.runner_up_bid_ids),
            "mission_id": mission_id,
            "mission_created": True,
        }
        if persist_warning:
            result_data["warning"] = persist_warning
        return ServiceResult(success=True, data=result_data)

    def cancel_listing(self, listing_id: str) -> ServiceResult:
        """Cancel a listing. Withdraws all submitted bids."""
        listing = self._listings.get(listing_id)
        if listing is None:
            return ServiceResult(
                success=False,
                errors=[f"Listing not found: {listing_id}"],
            )

        # Snapshot for rollback
        prev_listing_state = listing.state
        bid_snapshots = [
            (bid, bid.state) for bid in self._bids.get(listing_id, [])
        ]

        errors = ListingStateMachine.apply_transition(listing, ListingState.CANCELLED)
        if errors:
            return ServiceResult(success=False, errors=errors)

        # Withdraw all submitted bids
        for bid in self._bids.get(listing_id, []):
            if bid.state == BidState.SUBMITTED:
                bid.state = BidState.WITHDRAWN

        def _rollback() -> None:
            listing.state = prev_listing_state
            for bid_obj, prev_bid_state in bid_snapshots:
                bid_obj.state = prev_bid_state

        err = self._safe_persist(on_rollback=_rollback)
        if err:
            return ServiceResult(success=False, errors=[err])
        return ServiceResult(
            success=True,
            data={"listing_id": listing_id, "state": listing.state.value},
        )

    def search_listings(
        self,
        state: ListingState | None = None,
        domain_tags: list[str] | None = None,
        creator_id: str | None = None,
        limit: int = 20,
    ) -> ServiceResult:
        """Search for listings with optional filters."""
        results: list[dict[str, Any]] = []
        for listing in self._listings.values():
            if state is not None and listing.state != state:
                continue
            if creator_id is not None and listing.creator_id != creator_id:
                continue
            if domain_tags:
                if not any(tag in listing.domain_tags for tag in domain_tags):
                    continue
            bid_count = len([
                b for b in self._bids.get(listing.listing_id, [])
                if b.state == BidState.SUBMITTED
            ])
            results.append({
                "listing_id": listing.listing_id,
                "title": listing.title,
                "state": listing.state.value,
                "creator_id": listing.creator_id,
                "skill_requirements": len(listing.skill_requirements),
                "bid_count": bid_count,
                "domain_tags": listing.domain_tags,
            })
            if len(results) >= limit:
                break

        return ServiceResult(
            success=True,
            data={
                "listings": results,
                "total": len(results),
            },
        )

    def get_listing(self, listing_id: str) -> Optional[MarketListing]:
        """Retrieve a listing by ID."""
        return self._listings.get(listing_id)

    def get_bids(self, listing_id: str) -> list[Bid]:
        """Retrieve all bids for a listing."""
        return list(self._bids.get(listing_id, []))

    # ------------------------------------------------------------------
    # Mission lifecycle
    # ------------------------------------------------------------------

    def create_mission(
        self,
        mission_id: str,
        title: str,
        mission_class: MissionClass,
        domain_type: DomainType,
        worker_id: Optional[str] = None,
    ) -> ServiceResult:
        """Create a new mission in DRAFT state."""
        if mission_id in self._missions:
            return ServiceResult(
                success=False,
                errors=[f"Mission already exists: {mission_id}"],
            )

        tier = self._resolver.resolve_tier(mission_class)
        mission = Mission(
            mission_id=mission_id,
            mission_title=title,
            mission_class=mission_class,
            risk_tier=tier,
            domain_type=domain_type,
            worker_id=worker_id,
            created_utc=datetime.now(timezone.utc),
        )
        self._missions[mission_id] = mission

        # Record audit event (fail-closed: errors propagate)
        err = self._record_mission_event(mission, "created")
        if err:
            del self._missions[mission_id]
            return ServiceResult(success=False, errors=[err])

        # Audit event is now committed — do NOT rollback in-memory state
        persist_warning = self._safe_persist_post_audit()
        result_data: dict[str, Any] = {
            "mission_id": mission_id, "risk_tier": tier.value,
        }
        if persist_warning:
            result_data["warning"] = persist_warning
        return ServiceResult(success=True, data=result_data)

    def submit_mission(self, mission_id: str) -> ServiceResult:
        """Transition mission from DRAFT to SUBMITTED."""
        return self._transition_mission(mission_id, MissionState.SUBMITTED)

    def assign_reviewers(
        self,
        mission_id: str,
        seed: Optional[str] = None,
        min_trust: float = 0.0,
    ) -> ServiceResult:
        """Select and assign reviewers from the roster."""
        mission = self._missions.get(mission_id)
        if mission is None:
            return ServiceResult(success=False, errors=[f"Mission not found: {mission_id}"])

        result = self._selector.select(mission, seed=seed, min_trust=min_trust)
        if not result.success:
            return ServiceResult(success=False, errors=result.errors)

        # Validate the selection against policy
        validation_errors = self._reviewer_router.validate_assignment(
            mission, result.reviewers,
        )
        if validation_errors:
            return ServiceResult(success=False, errors=validation_errors)

        mission.reviewers = result.reviewers

        # Transition to ASSIGNED
        transition_result = self._transition_mission(mission_id, MissionState.ASSIGNED)
        if not transition_result.success:
            return transition_result

        # Transition to IN_REVIEW
        return self._transition_mission(mission_id, MissionState.IN_REVIEW)

    def submit_review(
        self,
        mission_id: str,
        reviewer_id: str,
        verdict: str,
        notes: str = "",
    ) -> ServiceResult:
        """Submit a review decision for a mission."""
        mission = self._missions.get(mission_id)
        if mission is None:
            return ServiceResult(success=False, errors=[f"Mission not found: {mission_id}"])

        try:
            verdict_enum = ReviewDecisionVerdict(verdict)
        except ValueError:
            return ServiceResult(
                success=False,
                errors=[f"Invalid verdict: {verdict}. Use APPROVE, REJECT, or ABSTAIN"],
            )

        decision = ReviewDecision(
            reviewer_id=reviewer_id,
            decision=verdict_enum,
            notes=notes,
            timestamp_utc=datetime.now(timezone.utc),
        )
        mission.review_decisions.append(decision)

        err = self._record_mission_event(mission, f"review:{reviewer_id}:{verdict}")
        if err:
            mission.review_decisions.pop()
            return ServiceResult(success=False, errors=[err])

        warning = self._safe_persist_post_audit()
        if warning:
            return ServiceResult(success=True, data={"warning": warning})
        return ServiceResult(success=True)

    def add_evidence(
        self,
        mission_id: str,
        artifact_hash: str,
        signature: str,
    ) -> ServiceResult:
        """Add an evidence record to a mission."""
        mission = self._missions.get(mission_id)
        if mission is None:
            return ServiceResult(success=False, errors=[f"Mission not found: {mission_id}"])

        record = EvidenceRecord(artifact_hash=artifact_hash, signature=signature)
        errors = self._evidence_validator.validate_record(record)
        if errors:
            return ServiceResult(success=False, errors=errors)

        mission.evidence.append(record)
        return ServiceResult(success=True)

    def complete_review(self, mission_id: str) -> ServiceResult:
        """Transition mission from IN_REVIEW to REVIEW_COMPLETE."""
        return self._transition_mission(mission_id, MissionState.REVIEW_COMPLETE)

    def approve_mission(self, mission_id: str) -> ServiceResult:
        """Approve a mission — routes through human gate if policy requires it.

        For R2+ missions with human_final_gate=true, this transitions to
        HUMAN_GATE_PENDING. Use human_gate_approve() to complete.
        For other missions, transitions directly to APPROVED.
        """
        mission = self._missions.get(mission_id)
        if mission is None:
            return ServiceResult(success=False, errors=[f"Mission not found: {mission_id}"])

        policy = self._resolver.tier_policy(mission.risk_tier)
        if policy.human_final_gate and not mission.human_final_approval:
            # Route to human gate — cannot skip
            return self._transition_mission(mission_id, MissionState.HUMAN_GATE_PENDING)

        result = self._transition_mission(mission_id, MissionState.APPROVED)
        if result.success:
            qa_result = self._assess_and_update_quality(mission_id)
            result.data["quality_assessment"] = qa_result.data
        return result

    def human_gate_approve(
        self,
        mission_id: str,
        approver_id: str,
    ) -> ServiceResult:
        """Human final approval for high-risk missions.

        This is the only path to APPROVED for missions that require
        human_final_gate. The approver must be a registered human actor.
        """
        mission = self._missions.get(mission_id)
        if mission is None:
            return ServiceResult(success=False, errors=[f"Mission not found: {mission_id}"])

        if mission.state != MissionState.HUMAN_GATE_PENDING:
            return ServiceResult(
                success=False,
                errors=[f"Mission {mission_id} not in HUMAN_GATE_PENDING state"],
            )

        # Verify approver is a registered human
        entry = self._roster.get(approver_id)
        if entry is None:
            return ServiceResult(
                success=False,
                errors=[f"Approver not found: {approver_id}"],
            )
        if entry.actor_kind != ActorKind.HUMAN:
            return ServiceResult(
                success=False,
                errors=[f"Human gate requires human approver; {approver_id} is {entry.actor_kind.value}"],
            )

        mission.human_final_approval = True

        err = self._record_mission_event(mission, f"human_gate_approve:{approver_id}")
        if err:
            mission.human_final_approval = False
            return ServiceResult(success=False, errors=[err])

        result = self._transition_mission(mission_id, MissionState.APPROVED)
        if result.success:
            qa_result = self._assess_and_update_quality(mission_id)
            result.data["quality_assessment"] = qa_result.data
        return result

    def human_gate_reject(
        self,
        mission_id: str,
        rejector_id: str,
    ) -> ServiceResult:
        """Human final rejection for high-risk missions."""
        mission = self._missions.get(mission_id)
        if mission is None:
            return ServiceResult(success=False, errors=[f"Mission not found: {mission_id}"])

        if mission.state != MissionState.HUMAN_GATE_PENDING:
            return ServiceResult(
                success=False,
                errors=[f"Mission {mission_id} not in HUMAN_GATE_PENDING state"],
            )

        # Verify rejector is a registered human
        entry = self._roster.get(rejector_id)
        if entry is None:
            return ServiceResult(
                success=False,
                errors=[f"Rejector not found: {rejector_id}"],
            )
        if entry.actor_kind != ActorKind.HUMAN:
            return ServiceResult(
                success=False,
                errors=[f"Human gate requires human actor; {rejector_id} is {entry.actor_kind.value}"],
            )

        err = self._record_mission_event(mission, f"human_gate_reject:{rejector_id}")
        if err:
            return ServiceResult(success=False, errors=[err])

        result = self._transition_mission(mission_id, MissionState.REJECTED)
        if result.success:
            qa_result = self._assess_and_update_quality(mission_id)
            result.data["quality_assessment"] = qa_result.data
        return result

    def get_mission(self, mission_id: str) -> Optional[Mission]:
        """Retrieve a mission by ID."""
        return self._missions.get(mission_id)

    # ------------------------------------------------------------------
    # Trust operations
    # ------------------------------------------------------------------

    def update_trust(
        self,
        actor_id: str,
        quality: float,
        reliability: float,
        volume: float,
        reason: str,
        effort: float = 0.0,
        mission_id: Optional[str] = None,
    ) -> ServiceResult:
        """Update an actor's trust score.

        Enforces machine recertification: after applying the trust update,
        checks recertification requirements for machine actors. Failures
        increment the recertification counter and may trigger quarantine
        or decommission per constitutional rules.
        """
        record = self._trust_records.get(actor_id.strip())
        if record is None:
            return ServiceResult(
                success=False,
                errors=[f"No trust record for actor: {actor_id}"],
            )

        # Trust freeze: actors on protected leave cannot gain or lose trust
        if self.is_actor_on_leave(actor_id.strip()):
            return ServiceResult(
                success=False,
                errors=[
                    f"Actor {actor_id.strip()} is on protected leave; "
                    f"trust is frozen (no gain, no loss)"
                ],
            )

        new_record, delta = self._trust_engine.apply_update(
            record, quality=quality, reliability=reliability,
            volume=volume, reason=reason, effort=effort,
            mission_id=mission_id,
        )

        # Snapshot roster state for rollback
        roster_entry = self._roster.get(actor_id)
        prior_roster_status = roster_entry.status if roster_entry else None

        # Machine recertification enforcement
        recert_issues: list[str] = []
        if new_record.actor_kind == ActorKind.MACHINE:
            recert_issues = self._trust_engine.check_recertification(new_record)
            if recert_issues:
                # Increment failure counter
                new_record = TrustRecord(
                    actor_id=new_record.actor_id,
                    actor_kind=new_record.actor_kind,
                    score=new_record.score,
                    quality=new_record.quality,
                    reliability=new_record.reliability,
                    volume=new_record.volume,
                    effort=new_record.effort,
                    quarantined=new_record.quarantined,
                    recertification_failures=new_record.recertification_failures + 1,
                    last_recertification_utc=new_record.last_recertification_utc,
                    decommissioned=new_record.decommissioned,
                    last_active_utc=new_record.last_active_utc,
                )
                # Check if decommission threshold reached
                decomm = self._resolver.decommission_rules()
                if new_record.recertification_failures >= decomm["M_RECERT_FAIL_MAX"]:
                    new_record = TrustRecord(
                        actor_id=new_record.actor_id,
                        actor_kind=new_record.actor_kind,
                        score=0.0,
                        quality=new_record.quality,
                        reliability=new_record.reliability,
                        volume=new_record.volume,
                        effort=new_record.effort,
                        quarantined=True,
                        recertification_failures=new_record.recertification_failures,
                        last_recertification_utc=new_record.last_recertification_utc,
                        decommissioned=True,
                        last_active_utc=new_record.last_active_utc,
                    )
                    # Update roster status
                    if roster_entry:
                        roster_entry.status = ActorStatus.DECOMMISSIONED

        self._trust_records[actor_id.strip()] = new_record

        # Update roster trust score
        if roster_entry:
            roster_entry.trust_score = new_record.score

        # Record event (fail-closed)
        err = self._record_trust_event(actor_id, delta)
        if err:
            # Full rollback: trust record, roster score, AND roster status
            self._trust_records[actor_id.strip()] = record
            if roster_entry:
                roster_entry.trust_score = record.score
                roster_entry.status = prior_roster_status
            return ServiceResult(success=False, errors=[err])

        # Audit event committed — do NOT rollback in-memory state
        persist_warning = self._safe_persist_post_audit()

        result_data: dict[str, Any] = {
            "actor_id": actor_id,
            "old_score": record.score,
            "new_score": new_record.score,
            "delta": delta.abs_delta,
            "suspended": delta.suspended,
        }
        if recert_issues:
            result_data["recertification_issues"] = recert_issues
            result_data["recertification_failures"] = new_record.recertification_failures
            result_data["decommissioned"] = new_record.decommissioned
        if persist_warning:
            result_data["warning"] = persist_warning

        return ServiceResult(success=True, data=result_data)

    def get_trust(self, actor_id: str) -> Optional[TrustRecord]:
        """Retrieve trust record for an actor."""
        return self._trust_records.get(actor_id.strip())

    def get_domain_trust(
        self, actor_id: str, domain: str,
    ) -> Optional[DomainTrustScore]:
        """Retrieve an actor's trust score for a specific domain."""
        record = self._trust_records.get(actor_id.strip())
        if record is None:
            return None
        return record.domain_scores.get(domain)

    def get_trust_status(self, actor_id: str) -> Optional[TrustStatus]:
        """Compute the full trust dashboard for an actor.

        Returns TrustStatus with days-until-half-life, urgency
        indicators, per-domain forecasts, and projected scores.
        Computed on-demand — no persistence needed.
        """
        record = self._trust_records.get(actor_id.strip())
        if record is None:
            return None
        return self._trust_engine.compute_decay_forecast(record)

    def decay_inactive_actors(self) -> ServiceResult:
        """Apply inactivity decay to all actors.

        Should be called periodically (e.g. daily). Decays both
        domain-specific and global trust for inactive actors.
        Differentiated by ActorKind: HUMAN 365-day half-life,
        MACHINE 90-day half-life.
        """
        if not self._resolver.has_skill_trust_config():
            return ServiceResult(
                success=False,
                errors=["No skill trust config loaded — decay not available"],
            )

        decayed_actors: list[dict[str, Any]] = []
        # Snapshot for rollback: {actor_id: (old_record, old_roster_score)}
        snapshots: dict[str, tuple[TrustRecord, float | None]] = {}

        for actor_id, record in list(self._trust_records.items()):
            # Skip actors on protected leave — trust is frozen
            if self.is_actor_on_leave(actor_id):
                continue
            new_record = self._trust_engine.apply_inactivity_decay(record)
            if new_record is not record:  # identity check — was actually decayed
                roster_entry = self._roster.get(actor_id)
                snapshots[actor_id] = (
                    record,
                    roster_entry.trust_score if roster_entry else None,
                )
                self._trust_records[actor_id] = new_record
                # Update roster trust score
                if roster_entry:
                    roster_entry.trust_score = new_record.score
                decayed_actors.append({
                    "actor_id": actor_id,
                    "old_score": record.score,
                    "new_score": new_record.score,
                })

        if decayed_actors:
            def _rollback() -> None:
                for s_aid, (old_rec, old_roster_score) in snapshots.items():
                    self._trust_records[s_aid] = old_rec
                    r_entry = self._roster.get(s_aid)
                    if r_entry and old_roster_score is not None:
                        r_entry.trust_score = old_roster_score

            err = self._safe_persist(on_rollback=_rollback)
            if err:
                return ServiceResult(success=False, errors=[err])

        return ServiceResult(
            success=True,
            data={
                "decayed_count": len(decayed_actors),
                "actors": decayed_actors,
            },
        )

    # ------------------------------------------------------------------
    # Protected leave
    # ------------------------------------------------------------------

    def request_leave(
        self,
        actor_id: str,
        category: LeaveCategory,
        reason_summary: str = "",
    ) -> ServiceResult:
        """Submit a protected leave request.

        Validates actor exists and is active, checks anti-gaming
        constraints, creates a PENDING leave record.
        """
        actor_id = actor_id.strip()
        entry = self._roster.get(actor_id)
        if entry is None:
            return ServiceResult(
                success=False, errors=[f"Actor not found: {actor_id}"],
            )
        # Protected leave is for human life events only
        if entry.actor_kind != ActorKind.HUMAN:
            return ServiceResult(
                success=False,
                errors=["Only human actors can request protected leave"],
            )
        # DEATH category must use petition_memorialisation() — third-party petitioned
        if category == LeaveCategory.DEATH:
            return ServiceResult(
                success=False,
                errors=[
                    "Death memorialisation must be petitioned by a third party "
                    "using petition_memorialisation(), not self-requested"
                ],
            )
        if not entry.is_available():
            return ServiceResult(
                success=False,
                errors=[f"Actor status is {entry.status.value}; must be active or probation"],
            )

        # Anti-gaming checks
        existing_leaves = [
            r for r in self._leave_records.values()
            if r.actor_id == actor_id
        ]
        violations = self._leave_engine.check_anti_gaming(
            actor_id, existing_leaves,
        )
        if violations:
            return ServiceResult(success=False, errors=violations)

        # Create PENDING record
        now = datetime.now(timezone.utc)
        self._leave_counter += 1
        leave_id = f"LEAVE-{self._leave_counter:06d}"

        record = LeaveRecord(
            leave_id=leave_id,
            actor_id=actor_id,
            category=category,
            state=LeaveState.PENDING,
            reason_summary=reason_summary,
            requested_utc=now,
        )
        self._leave_records[leave_id] = record

        # Three-step event recording
        err = self._record_leave_event(record, "requested")
        if err:
            del self._leave_records[leave_id]
            self._leave_counter -= 1
            return ServiceResult(success=False, errors=[err])

        warning = self._safe_persist_post_audit()
        data: dict[str, Any] = {"leave_id": leave_id, "state": record.state.value}
        if warning:
            data["warning"] = warning
        return ServiceResult(success=True, data=data)

    def adjudicate_leave(
        self,
        leave_id: str,
        adjudicator_id: str,
        verdict: AdjudicationVerdict,
        notes: str = "",
    ) -> ServiceResult:
        """Submit an adjudication verdict on a leave request.

        Validates adjudicator eligibility (human, domain trust, not self,
        not duplicate). If quorum is reached, transitions to APPROVED
        (activating trust freeze) or DENIED.
        """
        record = self._leave_records.get(leave_id)
        if record is None:
            return ServiceResult(
                success=False, errors=[f"Leave record not found: {leave_id}"],
            )
        if record.state != LeaveState.PENDING:
            return ServiceResult(
                success=False,
                errors=[f"Leave is {record.state.value}; can only adjudicate PENDING"],
            )

        # For death petitions, check if actor already memorialised by another record
        if record.category == LeaveCategory.DEATH:
            actor_entry = self._roster.get(record.actor_id)
            if actor_entry and actor_entry.status == ActorStatus.MEMORIALISED:
                return ServiceResult(
                    success=False,
                    errors=[f"Actor {record.actor_id} is already memorialised"],
                )

        adjudicator_id = adjudicator_id.strip()

        # Duplicate vote check
        for adj in record.adjudications:
            if adj.adjudicator_id == adjudicator_id:
                return ServiceResult(
                    success=False,
                    errors=[f"Adjudicator {adjudicator_id} has already voted"],
                )

        # Enforce max_adjudicators cap
        adj_config = self._resolver.leave_adjudication_config()
        max_adjudicators = adj_config.get("max_adjudicators")
        if max_adjudicators is not None and len(record.adjudications) >= max_adjudicators:
            return ServiceResult(
                success=False,
                errors=[
                    f"Maximum adjudicator cap reached ({max_adjudicators}); "
                    f"no further votes accepted"
                ],
            )

        # Eligibility check via engine
        adj_entry = self._roster.get(adjudicator_id)
        if adj_entry is None:
            return ServiceResult(
                success=False,
                errors=[f"Adjudicator not found: {adjudicator_id}"],
            )
        adj_trust = self._trust_records.get(adjudicator_id)
        if adj_trust is None:
            return ServiceResult(
                success=False,
                errors=[f"No trust record for adjudicator: {adjudicator_id}"],
            )

        eligibility = self._leave_engine.check_adjudicator_eligibility(
            adj_entry, adj_trust, record.category, record.actor_id,
        )
        if not eligibility.eligible:
            return ServiceResult(success=False, errors=eligibility.errors)

        # Snapshot for rollback
        old_adjudications = list(record.adjudications)
        old_state = record.state
        old_approved_utc = record.approved_utc
        old_denied_utc = record.denied_utc

        # Add adjudication
        now = datetime.now(timezone.utc)
        adjudication = LeaveAdjudication(
            adjudicator_id=adjudicator_id,
            verdict=verdict,
            domain_qualified=eligibility.qualifying_domain,
            trust_score_at_decision=adj_trust.score,
            notes=notes,
            timestamp_utc=now,
        )
        record.adjudications.append(adjudication)

        # Record adjudication event
        err = self._record_leave_event(record, "adjudicated")
        if err:
            record.adjudications = old_adjudications
            return ServiceResult(success=False, errors=[err])

        # Check quorum
        quorum_result = self._leave_engine.evaluate_quorum(record)
        activation_data: dict[str, Any] | None = None

        if quorum_result.quorum_reached:
            if quorum_result.approved:
                # Diversity check: non-abstain adjudicators must meet
                # configured org/region diversity thresholds
                non_abstain_entries: dict[str, RosterEntry] = {}
                for adj in record.adjudications:
                    if adj.verdict != AdjudicationVerdict.ABSTAIN:
                        e = self._roster.get(adj.adjudicator_id)
                        if e is not None:
                            non_abstain_entries[adj.adjudicator_id] = e
                diversity_violations = (
                    self._leave_engine.check_adjudicator_diversity(
                        non_abstain_entries,
                    )
                )
                if diversity_violations:
                    # Quorum count is met but diversity is not —
                    # leave stays PENDING, more adjudicators needed
                    warning = self._safe_persist_post_audit()
                    data_pending: dict[str, Any] = {
                        "leave_id": leave_id,
                        "state": record.state.value,
                        "quorum_reached": False,
                        "diversity_unmet": diversity_violations,
                        "approve_count": quorum_result.approve_count,
                        "deny_count": quorum_result.deny_count,
                        "abstain_count": quorum_result.abstain_count,
                    }
                    if warning:
                        data_pending["warning"] = warning
                    return ServiceResult(success=True, data=data_pending)

                # DEATH category → memorialise (seal forever)
                # All other categories → activate leave (temporary freeze)
                if record.category == LeaveCategory.DEATH:
                    activation_data = self._memorialise_account(record, now)
                    err = self._record_leave_event(record, "memorialised")
                    if err:
                        # Rollback memorialisation
                        self._undo_memorialisation(record, old_state,
                                                    old_approved_utc, old_adjudications)
                        return ServiceResult(success=False, errors=[err])
                else:
                    activation_data = self._activate_leave(record, now)
                    err = self._record_leave_event(record, "approved")
                    if err:
                        self._undo_leave_activation(record, old_state,
                                                    old_approved_utc, old_adjudications)
                        return ServiceResult(success=False, errors=[err])
            else:
                # Deny
                record.state = LeaveState.DENIED
                record.denied_utc = now
                err = self._record_leave_event(record, "denied")
                if err:
                    record.state = old_state
                    record.denied_utc = old_denied_utc
                    record.adjudications = old_adjudications
                    return ServiceResult(success=False, errors=[err])

        warning = self._safe_persist_post_audit()
        data: dict[str, Any] = {
            "leave_id": leave_id,
            "state": record.state.value,
            "quorum_reached": quorum_result.quorum_reached,
            "approve_count": quorum_result.approve_count,
            "deny_count": quorum_result.deny_count,
            "abstain_count": quorum_result.abstain_count,
        }
        if activation_data:
            data["trust_frozen"] = True
            data["trust_score_at_freeze"] = activation_data["trust_score_at_freeze"]
        if warning:
            data["warning"] = warning
        return ServiceResult(success=True, data=data)

    def return_from_leave(self, leave_id: str) -> ServiceResult:
        """Return an actor from active leave.

        Restores ACTIVE status. Resets last_active_utc to now so
        decay resumes from the return moment, not from the original
        last-activity. Trust score is preserved from the freeze.
        """
        record = self._leave_records.get(leave_id)
        if record is None:
            return ServiceResult(
                success=False, errors=[f"Leave record not found: {leave_id}"],
            )
        if record.state == LeaveState.MEMORIALISED:
            return ServiceResult(
                success=False,
                errors=[
                    "Cannot return from memorialised leave — "
                    "account is permanently sealed"
                ],
            )
        if record.state != LeaveState.ACTIVE:
            return ServiceResult(
                success=False,
                errors=[f"Leave is {record.state.value}; can only return from ACTIVE"],
            )

        now = datetime.now(timezone.utc)
        actor_id = record.actor_id

        # Snapshot for rollback
        entry = self._roster.get(actor_id)
        old_status = entry.status if entry else None
        trust = self._trust_records.get(actor_id)
        old_last_active = trust.last_active_utc if trust else None
        # Snapshot per-domain last_active timestamps for rollback
        old_domain_last_active: dict[str, Any] = {}
        if trust:
            for domain, ds in trust.domain_scores.items():
                if hasattr(ds, "last_active_utc"):
                    old_domain_last_active[domain] = ds.last_active_utc

        # Transition
        record.state = LeaveState.RETURNED
        record.returned_utc = now
        if entry:
            # Restore pre-leave status (prevents PROBATION → ACTIVE escalation)
            restored_status = ActorStatus.ACTIVE
            if record.pre_leave_status:
                try:
                    restored_status = ActorStatus(record.pre_leave_status)
                except ValueError:
                    restored_status = ActorStatus.ACTIVE
            entry.status = restored_status
        # Reset last_active to now — decay resumes from return
        if trust:
            trust.last_active_utc = now
            # Also reset domain last_active timestamps
            for ds in trust.domain_scores.values():
                if hasattr(ds, "last_active_utc"):
                    ds.last_active_utc = now

        err = self._record_leave_event(record, "returned")
        if err:
            record.state = LeaveState.ACTIVE
            record.returned_utc = None
            if entry and old_status is not None:
                entry.status = old_status
            if trust:
                if old_last_active is not None:
                    trust.last_active_utc = old_last_active
                # Restore per-domain timestamps
                for domain, old_ts in old_domain_last_active.items():
                    ds = trust.domain_scores.get(domain)
                    if ds and hasattr(ds, "last_active_utc"):
                        ds.last_active_utc = old_ts
            return ServiceResult(success=False, errors=[err])

        warning = self._safe_persist_post_audit()
        data: dict[str, Any] = {
            "leave_id": leave_id,
            "actor_id": actor_id,
            "state": record.state.value,
        }
        if warning:
            data["warning"] = warning
        return ServiceResult(success=True, data=data)

    def petition_memorialisation(
        self,
        actor_id: str,
        petitioner_id: str,
        reason_summary: str = "",
    ) -> ServiceResult:
        """Petition to memorialise a deceased actor's account.

        Filed by a third party (relative, friend, colleague) — not
        self-requested. Creates a PENDING leave record with category
        DEATH. The same quorum adjudication process applies: qualified
        professionals assess the evidence and vote.

        On approval, the account is permanently sealed:
        - Status becomes MEMORIALISED (not ON_LEAVE).
        - Trust frozen forever — no gain, no loss, no decay.
        - Account can never be reactivated.
        - The person's verified record stands honestly.
        """
        actor_id = actor_id.strip()
        petitioner_id = petitioner_id.strip()

        # Validate actor exists
        entry = self._roster.get(actor_id)
        if entry is None:
            return ServiceResult(
                success=False, errors=[f"Actor not found: {actor_id}"],
            )
        # Only human accounts can be memorialised
        if entry.actor_kind != ActorKind.HUMAN:
            return ServiceResult(
                success=False,
                errors=["Only human actors can be memorialised"],
            )
        # Cannot memorialise an already-memorialised account
        if entry.status == ActorStatus.MEMORIALISED:
            return ServiceResult(
                success=False,
                errors=[f"Actor {actor_id} is already memorialised"],
            )
        # Block duplicate death petitions — no parallel pending/active death records
        existing_death_leaves = [
            r for r in self._leave_records.values()
            if r.actor_id == actor_id
            and r.category == LeaveCategory.DEATH
            and r.state in (LeaveState.PENDING, LeaveState.ACTIVE, LeaveState.MEMORIALISED)
        ]
        if existing_death_leaves:
            return ServiceResult(
                success=False,
                errors=[
                    f"Actor {actor_id} already has an active death "
                    f"memorialisation record (state: {existing_death_leaves[0].state.value})"
                ],
            )

        # Petitioner must be a different registered human
        pet_entry = self._roster.get(petitioner_id)
        if pet_entry is None:
            return ServiceResult(
                success=False,
                errors=[f"Petitioner not found: {petitioner_id}"],
            )
        if petitioner_id == actor_id:
            return ServiceResult(
                success=False,
                errors=["Cannot petition memorialisation for yourself"],
            )
        if pet_entry.actor_kind != ActorKind.HUMAN:
            return ServiceResult(
                success=False,
                errors=["Only human actors can petition memorialisation"],
            )

        # Create PENDING death leave record
        now = datetime.now(timezone.utc)
        self._leave_counter += 1
        leave_id = f"LEAVE-{self._leave_counter:06d}"

        record = LeaveRecord(
            leave_id=leave_id,
            actor_id=actor_id,
            category=LeaveCategory.DEATH,
            state=LeaveState.PENDING,
            reason_summary=reason_summary,
            petitioner_id=petitioner_id,
            requested_utc=now,
        )
        self._leave_records[leave_id] = record

        err = self._record_leave_event(record, "requested")
        if err:
            del self._leave_records[leave_id]
            self._leave_counter -= 1
            return ServiceResult(success=False, errors=[err])

        warning = self._safe_persist_post_audit()
        data: dict[str, Any] = {"leave_id": leave_id, "state": record.state.value}
        if warning:
            data["warning"] = warning
        return ServiceResult(success=True, data=data)

    def _memorialise_account(
        self, record: LeaveRecord, now: datetime,
    ) -> dict[str, Any]:
        """Seal a deceased actor's account. Called when death quorum approves.

        - Snapshots trust (same as _activate_leave).
        - Sets actor status to MEMORIALISED (not ON_LEAVE).
        - Sets leave state to MEMORIALISED.
        - Account can never be reactivated.
        """
        actor_id = record.actor_id
        trust = self._trust_records.get(actor_id)
        entry = self._roster.get(actor_id)

        # Snapshot pre-memorialisation status
        if entry:
            record.pre_leave_status = entry.status.value

        # Snapshot trust state for permanent freeze
        if trust:
            record.trust_score_at_freeze = trust.score
            record.last_active_utc_at_freeze = trust.last_active_utc
            record.domain_scores_at_freeze = {
                domain: DomainTrustScore(
                    domain=ds.domain,
                    score=ds.score,
                    quality=ds.quality,
                    reliability=ds.reliability,
                    volume=ds.volume,
                    effort=ds.effort,
                    mission_count=ds.mission_count,
                    last_active_utc=ds.last_active_utc,
                )
                for domain, ds in trust.domain_scores.items()
                if isinstance(ds, DomainTrustScore)
            }

        # Seal the account
        record.state = LeaveState.MEMORIALISED
        record.approved_utc = now
        record.memorialised_utc = now
        if entry:
            entry.status = ActorStatus.MEMORIALISED

        return {
            "trust_score_at_freeze": record.trust_score_at_freeze,
            "memorialised": True,
        }

    def check_leave_expiries(self) -> ServiceResult:
        """Periodic sweep: auto-return actors whose leave has expired.

        Categories with duration limits (e.g., pregnancy: 365 days,
        child_care: 365 days) get an expires_utc at approval time.
        When now > expires_utc, the leave auto-transitions to RETURNED.
        Extension requires a new adjudication (same quorum process).
        """
        expired: list[dict[str, Any]] = []
        errors_found: list[str] = []

        for leave_id, record in list(self._leave_records.items()):
            if self._leave_engine.check_leave_expiry(record):
                result = self.return_from_leave(leave_id)
                if result.success:
                    expired.append({
                        "leave_id": leave_id,
                        "actor_id": record.actor_id,
                        "category": record.category.value,
                    })
                else:
                    errors_found.extend(result.errors)

        return ServiceResult(
            success=len(errors_found) == 0,
            errors=errors_found,
            data={"expired_count": len(expired), "expired": expired},
        )

    def get_leave_record(self, leave_id: str) -> Optional[LeaveRecord]:
        """Look up a leave record."""
        return self._leave_records.get(leave_id)

    def get_actor_leaves(self, actor_id: str) -> list[LeaveRecord]:
        """Get all leave records for an actor."""
        return [
            r for r in self._leave_records.values()
            if r.actor_id == actor_id.strip()
        ]

    def is_actor_on_leave(self, actor_id: str) -> bool:
        """Check if an actor has an ACTIVE or MEMORIALISED leave record.

        Both states freeze trust: ACTIVE is temporary, MEMORIALISED is
        permanent (death). Either way the constitutional guarantee is the
        same — no gain, no loss, decay clock stopped.
        """
        return any(
            r.state in (LeaveState.ACTIVE, LeaveState.MEMORIALISED)
            for r in self._leave_records.values()
            if r.actor_id == actor_id.strip()
        )

    def get_leave_status(self) -> dict[str, Any]:
        """System-wide leave statistics."""
        by_state: dict[str, int] = {}
        by_category: dict[str, int] = {}
        for r in self._leave_records.values():
            by_state[r.state.value] = by_state.get(r.state.value, 0) + 1
            if r.state in (LeaveState.ACTIVE, LeaveState.PENDING, LeaveState.MEMORIALISED):
                by_category[r.category.value] = by_category.get(r.category.value, 0) + 1
        return {
            "total_records": len(self._leave_records),
            "by_state": by_state,
            "active_by_category": by_category,
        }

    # ------------------------------------------------------------------
    # Protected leave — internal helpers
    # ------------------------------------------------------------------

    def _activate_leave(
        self, record: LeaveRecord, now: datetime,
    ) -> dict[str, Any]:
        """Activate an approved leave — snapshot trust, set ON_LEAVE.

        Returns activation data for the service result.
        """
        actor_id = record.actor_id
        trust = self._trust_records.get(actor_id)
        entry = self._roster.get(actor_id)

        # Snapshot pre-leave actor status (to restore on return)
        if entry:
            record.pre_leave_status = entry.status.value

        # Snapshot trust state for freeze
        if trust:
            record.trust_score_at_freeze = trust.score
            record.last_active_utc_at_freeze = trust.last_active_utc
            # Deep-copy domain scores
            record.domain_scores_at_freeze = {
                domain: DomainTrustScore(
                    domain=ds.domain,
                    score=ds.score,
                    quality=ds.quality,
                    reliability=ds.reliability,
                    volume=ds.volume,
                    effort=ds.effort,
                    mission_count=ds.mission_count,
                    last_active_utc=ds.last_active_utc,
                )
                for domain, ds in trust.domain_scores.items()
                if isinstance(ds, DomainTrustScore)
            }

        # Set leave state
        record.state = LeaveState.ACTIVE
        record.approved_utc = now

        # Compute expiry if category has duration limit
        record.expires_utc = self._leave_engine.compute_expires_utc(
            record.category, now,
        )
        if record.expires_utc:
            # Extract granted duration from config
            duration_config = self._resolver.leave_duration_config()
            overrides = duration_config.get("category_overrides", {})
            default_max = duration_config.get("default_max_days")
            record.granted_duration_days = overrides.get(
                record.category.value, default_max,
            )

        # Set roster status to ON_LEAVE
        if entry:
            entry.status = ActorStatus.ON_LEAVE

        return {
            "trust_score_at_freeze": record.trust_score_at_freeze,
            "expires_utc": (
                record.expires_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
                if record.expires_utc else None
            ),
        }

    def _undo_leave_activation(
        self,
        record: LeaveRecord,
        old_state: LeaveState,
        old_approved_utc: Optional[datetime],
        old_adjudications: list[LeaveAdjudication],
    ) -> None:
        """Rollback helper for a failed leave activation."""
        actor_id = record.actor_id
        record.state = old_state
        record.approved_utc = old_approved_utc
        record.adjudications = old_adjudications
        # Restore pre-leave status
        pre_status = record.pre_leave_status
        record.trust_score_at_freeze = None
        record.last_active_utc_at_freeze = None
        record.domain_scores_at_freeze = {}
        record.expires_utc = None
        record.granted_duration_days = None
        record.pre_leave_status = None
        entry = self._roster.get(actor_id)
        if entry:
            if pre_status:
                try:
                    entry.status = ActorStatus(pre_status)
                except ValueError:
                    entry.status = ActorStatus.ACTIVE
            else:
                entry.status = ActorStatus.ACTIVE

    def _undo_memorialisation(
        self,
        record: LeaveRecord,
        old_state: LeaveState,
        old_approved_utc: Optional[datetime],
        old_adjudications: list[LeaveAdjudication],
    ) -> None:
        """Rollback helper for a failed memorialisation."""
        actor_id = record.actor_id
        record.state = old_state
        record.approved_utc = old_approved_utc
        record.memorialised_utc = None
        record.adjudications = old_adjudications
        # Restore pre-memorialisation status
        pre_status = record.pre_leave_status
        record.trust_score_at_freeze = None
        record.last_active_utc_at_freeze = None
        record.domain_scores_at_freeze = {}
        record.pre_leave_status = None
        entry = self._roster.get(actor_id)
        if entry:
            if pre_status:
                try:
                    entry.status = ActorStatus(pre_status)
                except ValueError:
                    entry.status = ActorStatus.ACTIVE
            else:
                entry.status = ActorStatus.ACTIVE

    def _record_leave_event(
        self, record: LeaveRecord, action: str,
    ) -> Optional[str]:
        """Record a leave event. Returns error string or None.

        Three-step ordering (same pattern as all other event recording):
        1. Pre-check epoch availability (fail fast).
        2. Durable append (if it fails, epoch stays clean).
        3. Epoch hash insertion (guaranteed to succeed).
        """
        # 1. Pre-check: verify epoch is open
        epoch = self._epoch_service.current_epoch
        if epoch is None or epoch.closed:
            return (
                "Audit-trail failure (no epoch open): "
                "No open epoch — call open_epoch() first."
            )

        event_data = (
            f"{record.leave_id}:{record.actor_id}:{action}:"
            f"{datetime.now(timezone.utc).isoformat()}"
        )
        event_hash = "sha256:" + hashlib.sha256(event_data.encode()).hexdigest()

        # Map action to EventKind
        action_to_kind = {
            "requested": EventKind.LEAVE_REQUESTED,
            "adjudicated": EventKind.LEAVE_ADJUDICATED,
            "approved": EventKind.LEAVE_APPROVED,
            "denied": EventKind.LEAVE_DENIED,
            "returned": EventKind.LEAVE_RETURNED,
            "permanent": EventKind.LEAVE_PERMANENT,
            "memorialised": EventKind.LEAVE_MEMORIALISED,
        }
        event_kind = action_to_kind.get(action, EventKind.LEAVE_REQUESTED)

        # 2. Durable append
        if self._event_log is not None:
            try:
                event = EventRecord.create(
                    event_id=self._next_event_id(),
                    event_kind=event_kind,
                    actor_id=record.actor_id,
                    payload={
                        "leave_id": record.leave_id,
                        "actor_id": record.actor_id,
                        "category": record.category.value,
                        "action": action,
                        "state": record.state.value,
                        "event_hash": event_hash,
                    },
                )
                self._event_log.append(event)
            except (ValueError, OSError) as e:
                return f"Event log failure: {e}"

        # 3. Epoch hash insertion
        self._epoch_service.record_mission_event(event_hash)
        return None

    # ------------------------------------------------------------------
    # Quality assessment
    # ------------------------------------------------------------------

    def assess_quality(self, mission_id: str) -> ServiceResult:
        """Manually trigger quality assessment for a completed mission.

        Use this for:
        - Re-assessment after normative adjudication resolves
        - Debugging and auditing
        - Missions that were completed before the quality engine was active

        Automatically updates trust for worker and reviewers unless
        normative escalation is triggered.
        """
        return self._assess_and_update_quality(mission_id)

    def _assess_and_update_quality(self, mission_id: str) -> ServiceResult:
        """Internal: assess quality for a completed mission and update trust.

        Steps (fail-closed ordering):
        1. Validate mission is in terminal state.
        2. Run QualityEngine to derive worker + reviewer quality.
        3. If normative escalation triggered, return without trust update.
        4. Record quality assessment audit event.
        5. Update worker trust with derived quality.
        6. Update each reviewer's trust with their derived quality.
        7. Update reviewer assessment history sliding window.
        8. Persist state.
        """
        mission = self._missions.get(mission_id)
        if mission is None:
            return ServiceResult(
                success=False,
                errors=[f"Mission not found: {mission_id}"],
            )

        # Terminal state check (QualityEngine also validates, but fail early)
        terminal = {MissionState.APPROVED, MissionState.REJECTED}
        if mission.state not in terminal:
            return ServiceResult(
                success=False,
                errors=[
                    f"Quality assessment requires terminal state, "
                    f"got {mission.state.value}"
                ],
            )

        try:
            report = self._quality_engine.assess_mission(
                mission=mission,
                trust_records=self._trust_records,
                reviewer_histories=self._reviewer_assessment_history,
            )
        except ValueError as e:
            return ServiceResult(success=False, errors=[str(e)])

        # Normative escalation: skip auto trust update
        if report.normative_escalation_triggered:
            return ServiceResult(
                success=True,
                data={
                    "mission_id": mission_id,
                    "normative_escalation": True,
                    "worker_derived_quality": report.worker_assessment.derived_quality,
                    "message": (
                        "Normative escalation triggered — trust updates "
                        "deferred until human adjudication resolves."
                    ),
                },
            )

        # Record quality assessment audit event (fail-closed)
        err = self._record_quality_event(mission_id, report)
        if err:
            return ServiceResult(success=False, errors=[err])

        # Update worker trust with derived quality
        worker_result = self.update_trust(
            actor_id=report.worker_assessment.worker_id,
            quality=report.worker_assessment.derived_quality,
            reliability=self._trust_records.get(
                report.worker_assessment.worker_id, TrustRecord(
                    actor_id="", actor_kind=ActorKind.HUMAN, score=0.0,
                ),
            ).reliability,
            volume=self._trust_records.get(
                report.worker_assessment.worker_id, TrustRecord(
                    actor_id="", actor_kind=ActorKind.HUMAN, score=0.0,
                ),
            ).volume,
            reason=f"quality_assessment:{mission_id}",
            mission_id=mission_id,
        )

        # Update each reviewer's trust
        reviewer_results: list[dict[str, Any]] = []
        for ra in report.reviewer_assessments:
            reviewer_record = self._trust_records.get(ra.reviewer_id)
            if reviewer_record is None:
                continue  # Reviewer may have been removed

            rev_result = self.update_trust(
                actor_id=ra.reviewer_id,
                quality=ra.derived_quality,
                reliability=reviewer_record.reliability,
                volume=reviewer_record.volume,
                reason=f"reviewer_quality_assessment:{mission_id}",
                mission_id=mission_id,
            )
            reviewer_results.append({
                "reviewer_id": ra.reviewer_id,
                "derived_quality": ra.derived_quality,
                "alignment": ra.alignment_score,
                "calibration": ra.calibration_score,
                "trust_updated": rev_result.success,
            })

            # Update reviewer assessment history sliding window
            _, window_size = self._resolver.calibration_config()
            history = self._reviewer_assessment_history.get(ra.reviewer_id, [])
            history.append(ra)
            # Trim to window size
            if len(history) > window_size:
                history = history[-window_size:]
            self._reviewer_assessment_history[ra.reviewer_id] = history

        # Domain-specific trust update (if mission has skill requirements)
        domain_updates: list[dict[str, Any]] = []
        if (
            hasattr(report.worker_assessment, "domains")
            and report.worker_assessment.domains
            and self._resolver.has_skill_trust_config()
        ):
            worker_record = self._trust_records.get(
                report.worker_assessment.worker_id
            )
            if worker_record is not None:
                for domain in report.worker_assessment.domains:
                    # Get existing domain score components or use current record
                    existing_ds = worker_record.domain_scores.get(domain)
                    reliability = existing_ds.reliability if existing_ds else worker_record.reliability
                    volume = existing_ds.volume if existing_ds else worker_record.volume

                    new_record, domain_delta = self._trust_engine.apply_domain_update(
                        record=worker_record,
                        domain=domain,
                        quality=report.worker_assessment.derived_quality,
                        reliability=reliability,
                        volume=volume,
                        reason=f"domain_quality_assessment:{mission_id}",
                        mission_id=mission_id,
                    )
                    self._trust_records[report.worker_assessment.worker_id] = new_record
                    worker_record = new_record  # chain updates

                    # Update roster trust score to reflect new aggregate
                    roster_entry = self._roster.get(report.worker_assessment.worker_id)
                    if roster_entry:
                        roster_entry.trust_score = new_record.score

                    domain_updates.append({
                        "domain": domain,
                        "old_score": domain_delta.previous_score,
                        "new_score": domain_delta.new_score,
                    })

        # Skill outcome update (if mission has skill requirements)
        skill_update_data = None
        if mission.skill_requirements and mission.worker_id:
            approved = mission.state == MissionState.APPROVED
            skill_update_data = self._update_skills_from_outcome(
                mission.worker_id, mission, approved,
            )

        warning = self._safe_persist_post_audit()

        result_data: dict[str, Any] = {
            "mission_id": mission_id,
            "normative_escalation": False,
            "worker_derived_quality": report.worker_assessment.derived_quality,
            "worker_trust_updated": worker_result.success,
            "reviewer_assessments": reviewer_results,
        }
        if domain_updates:
            result_data["domain_trust_updates"] = domain_updates
        if skill_update_data:
            result_data["skill_updates"] = skill_update_data
        if warning:
            result_data["warning"] = warning

        return ServiceResult(
            success=True,
            data=result_data,
        )

    # ------------------------------------------------------------------
    # Epoch operations
    # ------------------------------------------------------------------

    def open_epoch(self, epoch_id: Optional[str] = None) -> ServiceResult:
        """Open a new commitment epoch."""
        try:
            eid = self._epoch_service.open_epoch(epoch_id)
            warning = self._safe_persist_post_audit()
            data: dict[str, Any] = {"epoch_id": eid}
            if warning:
                data["warning"] = warning
            return ServiceResult(success=True, data=data)
        except RuntimeError as e:
            return ServiceResult(success=False, errors=[str(e)])

    def close_epoch(
        self,
        beacon_round: int,
        chamber_nonce: Optional[str] = None,
    ) -> ServiceResult:
        """Close the current epoch and build the commitment record."""
        try:
            record = self._epoch_service.close_epoch(
                beacon_round=beacon_round,
                chamber_nonce=chamber_nonce,
            )
            warning = self._safe_persist_post_audit()
            data: dict[str, Any] = {
                "epoch_id": record.epoch_id,
                "previous_hash": self._epoch_service.previous_hash,
                "event_counts": self._epoch_service.epoch_event_counts(),
            }
            if warning:
                data["warning"] = warning
            return ServiceResult(success=True, data=data)
        except RuntimeError as e:
            return ServiceResult(success=False, errors=[str(e)])

    # ------------------------------------------------------------------
    # Status and queries
    # ------------------------------------------------------------------

    def status(self) -> dict[str, Any]:
        """Return system-wide status summary."""
        return {
            "version": "0.1.0",
            "actors": {
                "total": self._roster.count,
                "active": self._roster.active_count,
                "humans": self._roster.human_count,
            },
            "missions": {
                "total": len(self._missions),
                "by_state": self._count_missions_by_state(),
            },
            "market": {
                "total_listings": len(self._listings),
                "open_listings": sum(
                    1 for l in self._listings.values()
                    if l.state in (ListingState.OPEN, ListingState.ACCEPTING_BIDS)
                ),
                "total_bids": sum(len(b) for b in self._bids.values()),
            },
            "leave": {
                "total_records": len(self._leave_records),
                "active_leaves": sum(
                    1 for r in self._leave_records.values()
                    if r.state == LeaveState.ACTIVE
                ),
                "pending_requests": sum(
                    1 for r in self._leave_records.values()
                    if r.state == LeaveState.PENDING
                ),
            },
            "epochs": {
                "committed": len(self._epoch_service.committed_records),
                "anchored": len(self._epoch_service.anchor_records),
                "current_open": (
                    self._epoch_service.current_epoch is not None
                    and not self._epoch_service.current_epoch.closed
                ),
            },
            "persistence_degraded": self._persistence_degraded,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _transition_listing(
        self, listing_id: str, target: ListingState,
    ) -> ServiceResult:
        """Validate and apply a listing state transition.

        Fail-closed: if audit recording fails, the state transition
        is fully rolled back and an error is returned.
        """
        listing = self._listings.get(listing_id)
        if listing is None:
            return ServiceResult(
                success=False,
                errors=[f"Listing not found: {listing_id}"],
            )

        # Snapshot for rollback
        prior_state = listing.state
        prior_opened_utc = listing.opened_utc

        errors = ListingStateMachine.apply_transition(listing, target)
        if errors:
            return ServiceResult(success=False, errors=errors)

        if target == ListingState.OPEN:
            listing.opened_utc = datetime.now(timezone.utc)

        err = self._record_listing_event(listing, f"transition:{target.value}")
        if err:
            # Rollback: restore prior state and derived fields
            listing.state = prior_state
            listing.opened_utc = prior_opened_utc
            return ServiceResult(success=False, errors=[err])

        # Audit event committed — do NOT rollback in-memory state
        persist_warning = self._safe_persist_post_audit()
        result_data: dict[str, Any] = {
            "listing_id": listing_id, "state": listing.state.value,
        }
        if persist_warning:
            result_data["warning"] = persist_warning
        return ServiceResult(success=True, data=result_data)

    def _transition_mission(
        self, mission_id: str, target: MissionState,
    ) -> ServiceResult:
        mission = self._missions.get(mission_id)
        if mission is None:
            return ServiceResult(
                success=False, errors=[f"Mission not found: {mission_id}"],
            )

        errors = self._state_machine.transition(mission, target)
        if errors:
            return ServiceResult(success=False, errors=errors)

        # State machine validates but does not apply — caller applies on success
        previous_state = mission.state
        mission.state = target

        err = self._record_mission_event(mission, f"transition:{target.value}")
        if err:
            mission.state = previous_state  # Rollback
            return ServiceResult(success=False, errors=[err])

        warning = self._safe_persist_post_audit()
        data: dict[str, Any] = {"state": mission.state.value}
        if warning:
            data["warning"] = warning
        return ServiceResult(success=True, data=data)

    def _next_event_id(self) -> str:
        """Generate a monotonically increasing unique event ID."""
        self._event_counter += 1
        return f"EVT-{self._event_counter:08d}"

    def _record_mission_event(self, mission: Mission, action: str) -> Optional[str]:
        """Hash and record a mission event. Returns error string or None.

        Fail-closed: if no epoch is open, returns an error rather than
        silently dropping the audit event.

        Three-step ordering ensures no phantom records in either store:
        1. Pre-check epoch availability (fail fast — nothing written yet).
        2. Durable append (if it fails, epoch stays clean).
        3. Epoch hash insertion (guaranteed to succeed — already validated).
        """
        # 1. Pre-check: verify epoch is open before writing anything
        epoch = self._epoch_service.current_epoch
        if epoch is None or epoch.closed:
            return "Audit-trail failure (no epoch open): No open epoch — call open_epoch() first."

        event_data = f"{mission.mission_id}:{action}:{datetime.now(timezone.utc).isoformat()}"
        event_hash = "sha256:" + hashlib.sha256(event_data.encode()).hexdigest()

        # 2. Durable append — if this fails, epoch stays clean
        if self._event_log is not None:
            try:
                event = EventRecord.create(
                    event_id=self._next_event_id(),
                    event_kind=EventKind.MISSION_TRANSITION,
                    actor_id=mission.worker_id or "system",
                    payload={
                        "mission_id": mission.mission_id,
                        "action": action,
                        "event_hash": event_hash,
                    },
                )
                self._event_log.append(event)
            except (ValueError, OSError) as e:
                return f"Event log failure: {e}"

        # 3. Epoch hash insertion — epoch was validated open in step 1
        self._epoch_service.record_mission_event(event_hash)

        return None

    def _record_trust_event(self, actor_id: str, delta: TrustDelta) -> Optional[str]:
        """Hash and record a trust delta. Returns error string or None.

        Fail-closed: if no epoch is open, returns an error.

        Three-step ordering ensures no phantom records in either store:
        1. Pre-check epoch availability (fail fast — nothing written yet).
        2. Durable append (if it fails, epoch stays clean).
        3. Epoch hash insertion (guaranteed to succeed — already validated).
        """
        # 1. Pre-check: verify epoch is open before writing anything
        epoch = self._epoch_service.current_epoch
        if epoch is None or epoch.closed:
            return "Audit-trail failure (no epoch open): No open epoch — call open_epoch() first."

        event_data = f"{actor_id}:{delta.abs_delta}:{datetime.now(timezone.utc).isoformat()}"
        event_hash = "sha256:" + hashlib.sha256(event_data.encode()).hexdigest()

        # 2. Durable append — if this fails, epoch stays clean
        if self._event_log is not None:
            try:
                event = EventRecord.create(
                    event_id=self._next_event_id(),
                    event_kind=EventKind.TRUST_UPDATED,
                    actor_id=actor_id,
                    payload={
                        "delta": delta.abs_delta,
                        "suspended": delta.suspended,
                        "event_hash": event_hash,
                    },
                )
                self._event_log.append(event)
            except (ValueError, OSError) as e:
                return f"Event log failure: {e}"

        # 3. Epoch hash insertion — epoch was validated open in step 1
        self._epoch_service.record_trust_delta(event_hash)

        return None

    def _record_quality_event(
        self, mission_id: str, report: MissionQualityReport,
    ) -> Optional[str]:
        """Hash and record a quality assessment event. Returns error or None.

        Three-step ordering (same pattern as mission/trust events):
        1. Pre-check epoch availability.
        2. Durable append.
        3. Epoch hash insertion.
        """
        # 1. Pre-check: verify epoch is open before writing anything
        epoch = self._epoch_service.current_epoch
        if epoch is None or epoch.closed:
            return (
                "Audit-trail failure (no epoch open): "
                "No open epoch — call open_epoch() first."
            )

        event_data = (
            f"{mission_id}:quality_assessed:"
            f"{report.worker_assessment.derived_quality:.4f}:"
            f"{datetime.now(timezone.utc).isoformat()}"
        )
        event_hash = "sha256:" + hashlib.sha256(
            event_data.encode()
        ).hexdigest()

        # 2. Durable append — if this fails, epoch stays clean
        if self._event_log is not None:
            try:
                event = EventRecord.create(
                    event_id=self._next_event_id(),
                    event_kind=EventKind.QUALITY_ASSESSED,
                    actor_id=report.worker_assessment.worker_id,
                    payload={
                        "mission_id": mission_id,
                        "worker_quality": report.worker_assessment.derived_quality,
                        "reviewer_count": len(report.reviewer_assessments),
                        "normative_escalation": report.normative_escalation_triggered,
                        "event_hash": event_hash,
                    },
                )
                self._event_log.append(event)
            except (ValueError, OSError) as e:
                return f"Event log failure: {e}"

        # 3. Epoch hash insertion — epoch was validated open in step 1
        self._epoch_service.record_mission_event(event_hash)

        return None

    def _record_listing_event(
        self, listing: MarketListing, action: str,
    ) -> Optional[str]:
        """Record a listing event. Returns error string or None."""
        epoch = self._epoch_service.current_epoch
        if epoch is None or epoch.closed:
            return "Audit-trail failure (no epoch open): No open epoch — call open_epoch() first."

        event_data = f"{listing.listing_id}:{action}:{datetime.now(timezone.utc).isoformat()}"
        event_hash = "sha256:" + hashlib.sha256(event_data.encode()).hexdigest()

        if self._event_log is not None:
            try:
                event = EventRecord.create(
                    event_id=self._next_event_id(),
                    event_kind=EventKind.LISTING_CREATED if action == "created" else EventKind.LISTING_TRANSITION,
                    actor_id=listing.creator_id,
                    payload={
                        "listing_id": listing.listing_id,
                        "action": action,
                        "event_hash": event_hash,
                    },
                )
                self._event_log.append(event)
            except (ValueError, OSError) as e:
                return f"Event log failure: {e}"

        self._epoch_service.record_mission_event(event_hash)
        return None

    def _record_bid_event(self, bid: Bid) -> Optional[str]:
        """Record a bid submission event. Returns error string or None."""
        epoch = self._epoch_service.current_epoch
        if epoch is None or epoch.closed:
            return "Audit-trail failure (no epoch open): No open epoch — call open_epoch() first."

        event_data = f"{bid.bid_id}:{bid.listing_id}:{bid.worker_id}:{datetime.now(timezone.utc).isoformat()}"
        event_hash = "sha256:" + hashlib.sha256(event_data.encode()).hexdigest()

        if self._event_log is not None:
            try:
                event = EventRecord.create(
                    event_id=self._next_event_id(),
                    event_kind=EventKind.BID_SUBMITTED,
                    actor_id=bid.worker_id,
                    payload={
                        "bid_id": bid.bid_id,
                        "listing_id": bid.listing_id,
                        "worker_id": bid.worker_id,
                        "composite_score": bid.composite_score,
                        "event_hash": event_hash,
                    },
                )
                self._event_log.append(event)
            except (ValueError, OSError) as e:
                return f"Event log failure: {e}"

        self._epoch_service.record_mission_event(event_hash)
        return None

    def _record_allocation_event(
        self, listing: MarketListing, result: AllocationResult,
    ) -> Optional[str]:
        """Record a worker allocation event. Returns error string or None."""
        epoch = self._epoch_service.current_epoch
        if epoch is None or epoch.closed:
            return "Audit-trail failure (no epoch open): No open epoch — call open_epoch() first."

        event_data = (
            f"{listing.listing_id}:{result.selected_worker_id}:"
            f"{result.composite_score}:{datetime.now(timezone.utc).isoformat()}"
        )
        event_hash = "sha256:" + hashlib.sha256(event_data.encode()).hexdigest()

        if self._event_log is not None:
            try:
                event = EventRecord.create(
                    event_id=self._next_event_id(),
                    event_kind=EventKind.WORKER_ALLOCATED,
                    actor_id=listing.creator_id,
                    payload={
                        "listing_id": listing.listing_id,
                        "selected_bid_id": result.selected_bid_id,
                        "selected_worker_id": result.selected_worker_id,
                        "composite_score": result.composite_score,
                        "mission_id": listing.allocated_mission_id,
                        "event_hash": event_hash,
                    },
                )
                self._event_log.append(event)
            except (ValueError, OSError) as e:
                return f"Event log failure: {e}"

        self._epoch_service.record_mission_event(event_hash)
        return None

    def _persist_state(self) -> None:
        """Persist current state to the state store (if wired).

        NOTE: This method can raise OSError. High-impact mutators
        should use _safe_persist() instead for fail-closed behavior.
        """
        if self._state_store is None:
            return
        self._state_store.save_roster(self._roster)
        self._state_store.save_trust_records(self._trust_records)
        self._state_store.save_missions(self._missions)
        self._state_store.save_reviewer_histories(self._reviewer_assessment_history)
        self._state_store.save_skill_profiles(self._skill_profiles)
        self._state_store.save_listings(self._listings, self._bids)
        self._state_store.save_leave_records(self._leave_records)
        self._state_store.save_epoch_state(
            self._epoch_service.previous_hash,
            len(self._epoch_service.committed_records),
        )

    def _safe_persist(
        self,
        on_rollback: Optional[Callable[[], None]] = None,
    ) -> Optional[str]:
        """Persist state with fail-closed error handling (pre-audit mode).

        Use this BEFORE audit events have been committed. On failure:
        1. Executes the rollback callback to undo in-memory mutations.
        2. Returns an error string for the caller to include in
           a ServiceResult.

        On success, returns None.
        """
        try:
            self._persist_state()
            return None
        except OSError as e:
            if on_rollback is not None:
                on_rollback()
            return f"Persistence failure: {e}"

    def _safe_persist_post_audit(self) -> Optional[str]:
        """Persist state after audit events have been committed.

        MUST NOT rollback in-memory state — the audit trail is already
        durable. If persist fails, in-memory state remains correct
        (aligned with audit events), but StateStore is stale.

        Sets _persistence_degraded flag for operator awareness and
        returns a warning string (not a hard error).
        """
        try:
            self._persist_state()
            return None
        except OSError as e:
            self._persistence_degraded = True
            return f"Persistence degraded: {e} — state committed in audit trail but StateStore is stale"

    def _count_missions_by_state(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for m in self._missions.values():
            counts[m.state.value] = counts.get(m.state.value, 0) + 1
        return counts
