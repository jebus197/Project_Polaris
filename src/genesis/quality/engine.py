"""Quality assessment engine — derives worker and reviewer quality from mission outcomes.

Pure computation. No side effects, no persistence, no audit events.
The service layer handles all of that — this engine only computes.

Design mirrors TrustEngine: stateless methods, PolicyResolver for all thresholds.

Worker quality:
  Q_worker = w_c * consensus + w_e * evidence + w_x * complexity
  - consensus: weighted approval ratio (reviewer trust as weight)
  - evidence: evidence_count / tier_expected_count, capped at 1.0
  - complexity: tier multiplier (R0=0.80 .. R3=1.10)

Reviewer quality:
  Q_reviewer = w_a * alignment + w_c * calibration
  - alignment: vote vs final outcome match (dissent partially valued)
  - calibration: historical accuracy via sliding window
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from genesis.models.mission import (
    DomainType,
    Mission,
    MissionState,
    ReviewDecisionVerdict,
)
from genesis.models.quality import (
    MissionQualityReport,
    ReviewerQualityAssessment,
    WorkerQualityAssessment,
)
from genesis.models.trust import TrustRecord
from genesis.policy.resolver import PolicyResolver


def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    """Clamp a value to [lo, hi]."""
    return max(lo, min(hi, value))


class QualityEngine:
    """Derives quality scores from completed mission data.

    Usage:
        engine = QualityEngine(resolver)
        report = engine.assess_mission(
            mission=completed_mission,
            trust_records={"reviewer-1": record1, ...},
            reviewer_histories={"reviewer-1": [prev_assessments], ...},
        )
        # report.worker_assessment.derived_quality → feed to TrustEngine
        # report.reviewer_assessments[i].derived_quality → feed to TrustEngine
    """

    def __init__(self, resolver: PolicyResolver) -> None:
        self._resolver = resolver

    # ------------------------------------------------------------------
    # Public: full mission assessment
    # ------------------------------------------------------------------

    def assess_mission(
        self,
        mission: Mission,
        trust_records: dict[str, TrustRecord],
        reviewer_histories: dict[str, list[ReviewerQualityAssessment]] | None = None,
    ) -> MissionQualityReport:
        """Assess quality for a completed mission.

        Args:
            mission: Must be in a terminal state (APPROVED or REJECTED).
            trust_records: Trust records keyed by actor_id for weighting.
            reviewer_histories: Previous reviewer assessments for calibration.
                Keyed by reviewer_id. If None, all calibration scores default
                to 0.5 (neutral).

        Returns:
            MissionQualityReport with worker + reviewer assessments.

        Raises:
            ValueError: If mission is not in a terminal state or has no worker.
        """
        self._validate_mission(mission)

        if reviewer_histories is None:
            reviewer_histories = {}

        now = datetime.now(timezone.utc)

        # Worker assessment
        worker_assessment = self.assess_worker_quality(
            mission=mission,
            trust_records=trust_records,
            assessment_utc=now,
        )

        # Reviewer assessments
        reviewer_assessments: list[ReviewerQualityAssessment] = []
        for decision in mission.review_decisions:
            history = reviewer_histories.get(decision.reviewer_id, [])
            assessment = self.assess_reviewer_quality(
                reviewer_id=decision.reviewer_id,
                mission=mission,
                reviewer_history=history,
                assessment_utc=now,
            )
            reviewer_assessments.append(assessment)

        # Normative escalation check
        normative_escalation = self._check_normative_escalation(
            mission=mission,
            trust_records=trust_records,
        )

        return MissionQualityReport(
            mission_id=mission.mission_id,
            worker_assessment=worker_assessment,
            reviewer_assessments=reviewer_assessments,
            normative_escalation_triggered=normative_escalation,
            assessment_utc=now,
        )

    # ------------------------------------------------------------------
    # Public: individual assessments
    # ------------------------------------------------------------------

    def assess_worker_quality(
        self,
        mission: Mission,
        trust_records: dict[str, TrustRecord],
        assessment_utc: datetime | None = None,
    ) -> WorkerQualityAssessment:
        """Derive quality for the mission's worker.

        Returns a WorkerQualityAssessment with derived_quality in [0, 1].
        """
        self._validate_mission(mission)
        if assessment_utc is None:
            assessment_utc = datetime.now(timezone.utc)

        w_c, w_e, w_x = self._resolver.quality_worker_weights()

        consensus = self._compute_consensus_score(mission, trust_records)
        evidence = self._compute_evidence_score(mission)
        complexity = self._compute_complexity_factor(mission)

        derived = _clamp(w_c * consensus + w_e * evidence + w_x * complexity)

        return WorkerQualityAssessment(
            mission_id=mission.mission_id,
            worker_id=mission.worker_id,  # type: ignore[arg-type]
            consensus_score=consensus,
            evidence_score=evidence,
            complexity_factor=complexity,
            derived_quality=derived,
            assessment_utc=assessment_utc,
            details={
                "weights": {"consensus": w_c, "evidence": w_e, "complexity": w_x},
                "mission_state": mission.state.value,
                "risk_tier": mission.risk_tier.value,
            },
        )

    def assess_reviewer_quality(
        self,
        reviewer_id: str,
        mission: Mission,
        reviewer_history: list[ReviewerQualityAssessment] | None = None,
        assessment_utc: datetime | None = None,
    ) -> ReviewerQualityAssessment:
        """Derive quality for a single reviewer on a mission.

        Args:
            reviewer_id: The reviewer to assess.
            mission: The completed mission.
            reviewer_history: Past assessments for calibration scoring.
            assessment_utc: Optional timestamp override for testing.

        Returns:
            ReviewerQualityAssessment with derived_quality in [0, 1].
        """
        self._validate_mission(mission)
        if assessment_utc is None:
            assessment_utc = datetime.now(timezone.utc)
        if reviewer_history is None:
            reviewer_history = []

        w_a, w_cal = self._resolver.quality_reviewer_weights()

        alignment = self._compute_alignment_score(reviewer_id, mission)
        calibration = self._compute_calibration_score(
            reviewer_id, reviewer_history,
        )

        derived = _clamp(w_a * alignment + w_cal * calibration)

        return ReviewerQualityAssessment(
            reviewer_id=reviewer_id,
            mission_id=mission.mission_id,
            alignment_score=alignment,
            calibration_score=calibration,
            derived_quality=derived,
            assessment_utc=assessment_utc,
            details={
                "weights": {"alignment": w_a, "calibration": w_cal},
                "mission_state": mission.state.value,
            },
        )

    # ------------------------------------------------------------------
    # Private: consensus score
    # ------------------------------------------------------------------

    def _compute_consensus_score(
        self,
        mission: Mission,
        trust_records: dict[str, TrustRecord],
    ) -> float:
        """Weighted approval ratio.

        Each reviewer's vote is weighted by their trust score.
        APPROVE contributes its weight; REJECT contributes zero.
        ABSTAIN votes are excluded from both numerator and denominator.

        If all reviewers abstained or no decisions exist, returns 0.0.
        If mission was REJECTED, the consensus still reflects what happened
        — the trust update uses the derived quality which will be low for
        a rejected mission (low consensus → low worker quality → quality
        gate may block trust gain).
        """
        approve_weight = 0.0
        total_weight = 0.0

        for decision in mission.review_decisions:
            if decision.decision == ReviewDecisionVerdict.ABSTAIN:
                continue

            # Look up reviewer's trust; default to 1.0 if not in records
            # (defensive — should always be present in practice)
            record = trust_records.get(decision.reviewer_id)
            weight = record.score if record is not None else 1.0

            total_weight += weight

            if decision.decision == ReviewDecisionVerdict.APPROVE:
                approve_weight += weight

        if total_weight == 0.0:
            return 0.0

        return approve_weight / total_weight

    # ------------------------------------------------------------------
    # Private: evidence score
    # ------------------------------------------------------------------

    def _compute_evidence_score(self, mission: Mission) -> float:
        """Evidence thoroughness: actual / expected, capped at 1.0.

        Zero evidence always yields 0.0, even if tier expects zero (defensive).
        """
        expectations = self._resolver.evidence_expectations()
        expected = expectations.get(mission.risk_tier.value, 1)

        actual = len(mission.evidence)

        if actual == 0:
            return 0.0
        if expected == 0:
            # Defensive: if config expects zero evidence, any evidence → 1.0
            return 1.0

        return _clamp(actual / expected)

    # ------------------------------------------------------------------
    # Private: complexity factor
    # ------------------------------------------------------------------

    def _compute_complexity_factor(self, mission: Mission) -> float:
        """Tier-based complexity multiplier.

        Higher-risk missions get more quality credit when approved.
        The multiplier is used directly as the complexity component.
        """
        multipliers = self._resolver.complexity_multipliers()
        return multipliers.get(mission.risk_tier.value, 1.0)

    # ------------------------------------------------------------------
    # Private: reviewer alignment
    # ------------------------------------------------------------------

    def _compute_alignment_score(
        self, reviewer_id: str, mission: Mission,
    ) -> float:
        """How well did the reviewer's vote match the final outcome?

        Score table (from constitutional_params.json):
        - correct_approve: approved mission, reviewer voted APPROVE → 1.0
        - correct_reject: rejected mission, reviewer voted REJECT → 1.0
        - wrong_reject: approved mission, reviewer voted REJECT → 0.3 (dissent valued)
        - wrong_approve: rejected mission, reviewer voted APPROVE → 0.2 (rubber-stamp penalized)
        - abstain: any outcome → 0.5 (neutral)
        """
        scores = self._resolver.reviewer_alignment_scores()

        # Find this reviewer's decision
        decision = None
        for d in mission.review_decisions:
            if d.reviewer_id == reviewer_id:
                decision = d
                break

        if decision is None:
            # Reviewer assigned but no decision recorded — treat as abstain
            return scores.get("abstain", 0.5)

        if decision.decision == ReviewDecisionVerdict.ABSTAIN:
            return scores.get("abstain", 0.5)

        mission_approved = mission.state == MissionState.APPROVED

        if mission_approved:
            if decision.decision == ReviewDecisionVerdict.APPROVE:
                return scores.get("correct_approve", 1.0)
            else:  # REJECT
                return scores.get("wrong_reject", 0.3)
        else:
            # Mission rejected
            if decision.decision == ReviewDecisionVerdict.REJECT:
                return scores.get("correct_reject", 1.0)
            else:  # APPROVE
                return scores.get("wrong_approve", 0.2)

    # ------------------------------------------------------------------
    # Private: reviewer calibration
    # ------------------------------------------------------------------

    def _compute_calibration_score(
        self,
        reviewer_id: str,
        reviewer_history: list[ReviewerQualityAssessment],
    ) -> float:
        """Historical accuracy: is the reviewer too lenient or too strict?

        Uses a sliding window of past alignment scores.
        If history < min_history, returns neutral 0.5.
        Otherwise: 1.0 - 2.0 * |reviewer_mean_alignment - 0.5|

        This penalizes extremes — a reviewer who always scores 1.0 (pure
        follower) or always 0.2 (pure contrarian) gets a lower calibration
        than one whose alignment varies with circumstances.

        We use alignment_score from past assessments rather than raw vote
        counts, which already encodes the direction-aware scoring.
        """
        min_history, window_size = self._resolver.calibration_config()

        if len(reviewer_history) < min_history:
            return 0.5  # Neutral — insufficient data

        # Take the most recent window_size assessments
        recent = reviewer_history[-window_size:]

        mean_alignment = sum(a.alignment_score for a in recent) / len(recent)

        # Penalize extremes: perfect mean (1.0) → 0.0, neutral mean (0.5) → 1.0
        calibration = _clamp(1.0 - 2.0 * abs(mean_alignment - 0.5))

        return calibration

    # ------------------------------------------------------------------
    # Private: normative escalation
    # ------------------------------------------------------------------

    def _check_normative_escalation(
        self,
        mission: Mission,
        trust_records: dict[str, TrustRecord],
    ) -> bool:
        """Check if normative escalation should be triggered.

        Triggers when:
        1. Mission domain_type is NORMATIVE or MIXED, AND
        2. Raw consensus score < NORMATIVE_AGREEMENT_THRESHOLD

        When triggered, the service layer should skip automatic trust
        updates and escalate to human adjudication.
        """
        if mission.domain_type == DomainType.OBJECTIVE:
            return False

        threshold = self._resolver.normative_agreement_threshold()
        consensus = self._compute_consensus_score(mission, trust_records)

        return consensus < threshold

    # ------------------------------------------------------------------
    # Private: validation
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_mission(mission: Mission) -> None:
        """Validate mission is in a terminal state with a worker."""
        terminal = {MissionState.APPROVED, MissionState.REJECTED}
        if mission.state not in terminal:
            raise ValueError(
                f"Quality assessment requires terminal mission state "
                f"(APPROVED or REJECTED), got {mission.state.value}"
            )
        if not mission.worker_id:
            raise ValueError(
                f"Mission {mission.mission_id} has no worker_id — "
                f"cannot assess worker quality"
            )
