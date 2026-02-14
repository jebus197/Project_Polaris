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
from typing import Any, Optional

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
from genesis.models.trust import ActorKind, TrustDelta, TrustRecord
from genesis.persistence.event_log import EventLog, EventRecord, EventKind
from genesis.persistence.state_store import StateStore
from genesis.policy.resolver import PolicyResolver
from genesis.quality.engine import QualityEngine
from genesis.review.roster import ActorRoster, ActorStatus, RosterEntry
from genesis.review.selector import ReviewerSelector, SelectionResult
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

        # Persistence layer (optional — in-memory if not provided)
        self._event_log = event_log
        self._state_store = state_store

        # Load persisted state or start fresh
        if state_store is not None:
            self._roster = state_store.load_roster()
            self._trust_records = state_store.load_trust_records()
            self._missions = state_store.load_missions()
            self._reviewer_assessment_history = state_store.load_reviewer_histories()
            stored_hash, _ = state_store.load_epoch_state()
            self._epoch_service = EpochService(resolver, stored_hash)
        else:
            self._roster = ActorRoster()
            self._trust_records: dict[str, TrustRecord] = {}
            self._missions: dict[str, Mission] = {}
            self._reviewer_assessment_history: dict[str, list[ReviewerQualityAssessment]] = {}
            self._epoch_service = EpochService(resolver, previous_hash)

        self._selector = ReviewerSelector(resolver, self._roster)
        # Initialize counter from persisted log to avoid ID collision on restart
        self._event_counter = event_log.count if event_log is not None else 0

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

            self._trust_records[actor_id.strip()] = TrustRecord(
                actor_id=actor_id.strip(),
                actor_kind=actor_kind,
                score=initial_trust,
            )

            self._persist_state()
            return ServiceResult(success=True, data={"actor_id": actor_id.strip()})
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
        entry.status = ActorStatus.QUARANTINED
        trust = self._trust_records.get(actor_id.strip())
        if trust:
            trust.quarantined = True
        self._persist_state()
        return ServiceResult(success=True)

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

        self._persist_state()
        return ServiceResult(
            success=True,
            data={"mission_id": mission_id, "risk_tier": tier.value},
        )

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

        self._persist_state()
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

        self._persist_state()

        result_data = {
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

        return ServiceResult(success=True, data=result_data)

    def get_trust(self, actor_id: str) -> Optional[TrustRecord]:
        """Retrieve trust record for an actor."""
        return self._trust_records.get(actor_id.strip())

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

        self._persist_state()

        return ServiceResult(
            success=True,
            data={
                "mission_id": mission_id,
                "normative_escalation": False,
                "worker_derived_quality": report.worker_assessment.derived_quality,
                "worker_trust_updated": worker_result.success,
                "reviewer_assessments": reviewer_results,
            },
        )

    # ------------------------------------------------------------------
    # Epoch operations
    # ------------------------------------------------------------------

    def open_epoch(self, epoch_id: Optional[str] = None) -> ServiceResult:
        """Open a new commitment epoch."""
        try:
            eid = self._epoch_service.open_epoch(epoch_id)
            self._persist_state()
            return ServiceResult(success=True, data={"epoch_id": eid})
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
            self._persist_state()
            return ServiceResult(
                success=True,
                data={
                    "epoch_id": record.epoch_id,
                    "previous_hash": self._epoch_service.previous_hash,
                    "event_counts": self._epoch_service.epoch_event_counts(),
                },
            )
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
            "epochs": {
                "committed": len(self._epoch_service.committed_records),
                "anchored": len(self._epoch_service.anchor_records),
                "current_open": (
                    self._epoch_service.current_epoch is not None
                    and not self._epoch_service.current_epoch.closed
                ),
            },
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

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

        self._persist_state()
        return ServiceResult(success=True, data={"state": mission.state.value})

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

    def _persist_state(self) -> None:
        """Persist current state to the state store (if wired)."""
        if self._state_store is None:
            return
        self._state_store.save_roster(self._roster)
        self._state_store.save_trust_records(self._trust_records)
        self._state_store.save_missions(self._missions)
        self._state_store.save_reviewer_histories(self._reviewer_assessment_history)
        self._state_store.save_epoch_state(
            self._epoch_service.previous_hash,
            len(self._epoch_service.committed_records),
        )

    def _count_missions_by_state(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for m in self._missions.values():
            counts[m.state.value] = counts.get(m.state.value, 0) + 1
        return counts
