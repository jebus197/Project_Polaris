"""Tests for quality assessment engine — proves quality derivation is correct.

Covers:
- Consensus scoring (unanimous, mixed, all-abstain, trust weighting)
- Evidence scoring (sufficient, partial, zero, excess capped)
- Complexity factors (monotonically increasing R0 → R3)
- Worker quality end-to-end (perfect mission, rejected mission, clamping)
- Reviewer alignment (all 5 verdict × outcome combinations)
- Reviewer calibration (insufficient history, neutral, extreme)
- Normative escalation triggering
- Precondition validation (non-terminal mission, no worker_id)
"""

import pytest
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
from genesis.models.quality import ReviewerQualityAssessment
from genesis.models.trust import ActorKind, TrustRecord
from genesis.policy.resolver import PolicyResolver
from genesis.quality.engine import QualityEngine


CONFIG_DIR = Path(__file__).resolve().parents[1] / "config"
NOW = datetime(2026, 2, 14, 12, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def resolver() -> PolicyResolver:
    return PolicyResolver.from_config_dir(CONFIG_DIR)


@pytest.fixture
def engine(resolver: PolicyResolver) -> QualityEngine:
    return QualityEngine(resolver)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _trust_record(actor_id: str, score: float = 0.8) -> TrustRecord:
    return TrustRecord(
        actor_id=actor_id,
        actor_kind=ActorKind.MACHINE,
        score=score,
    )


def _evidence(n: int = 1) -> list[EvidenceRecord]:
    return [
        EvidenceRecord(artifact_hash=f"sha256:hash{i}", signature=f"sig{i}")
        for i in range(n)
    ]


def _reviewer(rid: str) -> Reviewer:
    return Reviewer(
        id=rid,
        model_family="gpt",
        method_type="reasoning_model",
        region="us",
        organization="org-a",
    )


def _approved_mission(
    tier: RiskTier = RiskTier.R1,
    domain: DomainType = DomainType.OBJECTIVE,
    decisions: list[ReviewDecision] | None = None,
    evidence_count: int = 2,
    worker_id: str = "worker-1",
) -> Mission:
    """Build an APPROVED mission with sensible defaults."""
    if decisions is None:
        decisions = [
            ReviewDecision(reviewer_id="rev-1", decision=ReviewDecisionVerdict.APPROVE),
            ReviewDecision(reviewer_id="rev-2", decision=ReviewDecisionVerdict.APPROVE),
        ]
    return Mission(
        mission_id="mission-001",
        mission_title="Test Mission",
        mission_class=MissionClass.INTERNAL_OPERATIONS_CHANGE,
        risk_tier=tier,
        domain_type=domain,
        state=MissionState.APPROVED,
        worker_id=worker_id,
        reviewers=[_reviewer(d.reviewer_id) for d in decisions],
        review_decisions=decisions,
        evidence=_evidence(evidence_count),
    )


def _rejected_mission(
    tier: RiskTier = RiskTier.R1,
    domain: DomainType = DomainType.OBJECTIVE,
    decisions: list[ReviewDecision] | None = None,
    evidence_count: int = 2,
) -> Mission:
    """Build a REJECTED mission."""
    if decisions is None:
        decisions = [
            ReviewDecision(reviewer_id="rev-1", decision=ReviewDecisionVerdict.REJECT),
            ReviewDecision(reviewer_id="rev-2", decision=ReviewDecisionVerdict.REJECT),
        ]
    return Mission(
        mission_id="mission-002",
        mission_title="Rejected Mission",
        mission_class=MissionClass.INTERNAL_OPERATIONS_CHANGE,
        risk_tier=tier,
        domain_type=domain,
        state=MissionState.REJECTED,
        worker_id="worker-1",
        reviewers=[_reviewer(d.reviewer_id) for d in decisions],
        review_decisions=decisions,
        evidence=_evidence(evidence_count),
    )


def _default_trust_records() -> dict[str, TrustRecord]:
    """Trust records for rev-1 and rev-2 with equal trust."""
    return {
        "rev-1": _trust_record("rev-1", 0.8),
        "rev-2": _trust_record("rev-2", 0.8),
    }


def _reviewer_assessment(
    alignment: float = 0.5,
    reviewer_id: str = "rev-1",
) -> ReviewerQualityAssessment:
    """Helper for building reviewer history entries."""
    return ReviewerQualityAssessment(
        reviewer_id=reviewer_id,
        mission_id="past-mission",
        alignment_score=alignment,
        calibration_score=0.5,
        derived_quality=0.5,
        assessment_utc=NOW,
    )


# ===================================================================
# Consensus scoring
# ===================================================================

class TestConsensusScore:
    def test_unanimous_approve(self, engine: QualityEngine) -> None:
        """All reviewers approve → consensus = 1.0."""
        mission = _approved_mission()
        records = _default_trust_records()
        report = engine.assess_mission(mission, records)
        assert report.worker_assessment.consensus_score == pytest.approx(1.0)

    def test_unanimous_reject(self, engine: QualityEngine) -> None:
        """All reviewers reject → consensus = 0.0."""
        mission = _rejected_mission()
        records = _default_trust_records()
        report = engine.assess_mission(mission, records)
        assert report.worker_assessment.consensus_score == pytest.approx(0.0)

    def test_mixed_votes_equal_trust(self, engine: QualityEngine) -> None:
        """One approve, one reject with equal trust → 0.5."""
        decisions = [
            ReviewDecision(reviewer_id="rev-1", decision=ReviewDecisionVerdict.APPROVE),
            ReviewDecision(reviewer_id="rev-2", decision=ReviewDecisionVerdict.REJECT),
        ]
        mission = _approved_mission(decisions=decisions)
        records = _default_trust_records()
        report = engine.assess_mission(mission, records)
        assert report.worker_assessment.consensus_score == pytest.approx(0.5)

    def test_mixed_votes_unequal_trust(self, engine: QualityEngine) -> None:
        """Higher trust on approver → consensus > 0.5."""
        decisions = [
            ReviewDecision(reviewer_id="rev-1", decision=ReviewDecisionVerdict.APPROVE),
            ReviewDecision(reviewer_id="rev-2", decision=ReviewDecisionVerdict.REJECT),
        ]
        mission = _approved_mission(decisions=decisions)
        records = {
            "rev-1": _trust_record("rev-1", 0.9),
            "rev-2": _trust_record("rev-2", 0.3),
        }
        report = engine.assess_mission(mission, records)
        expected = 0.9 / (0.9 + 0.3)
        assert report.worker_assessment.consensus_score == pytest.approx(expected)

    def test_all_abstain(self, engine: QualityEngine) -> None:
        """All abstain → consensus = 0.0."""
        decisions = [
            ReviewDecision(reviewer_id="rev-1", decision=ReviewDecisionVerdict.ABSTAIN),
            ReviewDecision(reviewer_id="rev-2", decision=ReviewDecisionVerdict.ABSTAIN),
        ]
        mission = _approved_mission(decisions=decisions)
        records = _default_trust_records()
        report = engine.assess_mission(mission, records)
        assert report.worker_assessment.consensus_score == pytest.approx(0.0)

    def test_abstain_excluded_from_denominator(self, engine: QualityEngine) -> None:
        """One approve, one abstain → consensus = 1.0 (abstain excluded)."""
        decisions = [
            ReviewDecision(reviewer_id="rev-1", decision=ReviewDecisionVerdict.APPROVE),
            ReviewDecision(reviewer_id="rev-2", decision=ReviewDecisionVerdict.ABSTAIN),
        ]
        mission = _approved_mission(decisions=decisions)
        records = _default_trust_records()
        report = engine.assess_mission(mission, records)
        assert report.worker_assessment.consensus_score == pytest.approx(1.0)

    def test_no_decisions(self, engine: QualityEngine) -> None:
        """No review decisions → consensus = 0.0."""
        mission = _approved_mission(decisions=[])
        records = {}
        report = engine.assess_mission(mission, records)
        assert report.worker_assessment.consensus_score == pytest.approx(0.0)


# ===================================================================
# Evidence scoring
# ===================================================================

class TestEvidenceScore:
    def test_sufficient_evidence(self, engine: QualityEngine) -> None:
        """Evidence count meets expectation → 1.0."""
        # R1 expects 2 evidence items
        mission = _approved_mission(tier=RiskTier.R1, evidence_count=2)
        records = _default_trust_records()
        report = engine.assess_mission(mission, records)
        assert report.worker_assessment.evidence_score == pytest.approx(1.0)

    def test_excess_evidence_capped(self, engine: QualityEngine) -> None:
        """More evidence than expected → still 1.0 (capped)."""
        mission = _approved_mission(tier=RiskTier.R1, evidence_count=10)
        records = _default_trust_records()
        report = engine.assess_mission(mission, records)
        assert report.worker_assessment.evidence_score == pytest.approx(1.0)

    def test_partial_evidence(self, engine: QualityEngine) -> None:
        """Half the expected evidence → 0.5."""
        # R2 expects 3 evidence items; provide 1
        mission = _approved_mission(tier=RiskTier.R2, evidence_count=1)
        records = _default_trust_records()
        report = engine.assess_mission(mission, records)
        expected = 1.0 / 3.0
        assert report.worker_assessment.evidence_score == pytest.approx(expected)

    def test_zero_evidence(self, engine: QualityEngine) -> None:
        """No evidence → 0.0."""
        mission = _approved_mission(evidence_count=0)
        records = _default_trust_records()
        report = engine.assess_mission(mission, records)
        assert report.worker_assessment.evidence_score == pytest.approx(0.0)


# ===================================================================
# Complexity factor
# ===================================================================

class TestComplexityFactor:
    def test_tier_multipliers_monotonic(self, engine: QualityEngine) -> None:
        """Higher tiers yield higher complexity factors."""
        factors = []
        for tier in [RiskTier.R0, RiskTier.R1, RiskTier.R2, RiskTier.R3]:
            mission = _approved_mission(tier=tier)
            records = _default_trust_records()
            report = engine.assess_mission(mission, records)
            factors.append(report.worker_assessment.complexity_factor)

        # R0=0.80, R1=0.90, R2=1.00, R3=1.10
        assert factors == sorted(factors)
        assert factors[0] < factors[-1]

    def test_r0_complexity(self, engine: QualityEngine) -> None:
        mission = _approved_mission(tier=RiskTier.R0, evidence_count=1)
        records = _default_trust_records()
        report = engine.assess_mission(mission, records)
        assert report.worker_assessment.complexity_factor == pytest.approx(0.80)

    def test_r3_complexity(self, engine: QualityEngine) -> None:
        mission = _approved_mission(tier=RiskTier.R3, evidence_count=3)
        records = _default_trust_records()
        report = engine.assess_mission(mission, records)
        assert report.worker_assessment.complexity_factor == pytest.approx(1.10)


# ===================================================================
# Worker quality end-to-end
# ===================================================================

class TestWorkerQuality:
    def test_perfect_approved_mission(self, engine: QualityEngine) -> None:
        """Unanimous approval, full evidence, high tier → high quality."""
        mission = _approved_mission(tier=RiskTier.R2, evidence_count=3)
        records = _default_trust_records()
        report = engine.assess_mission(mission, records)
        q = report.worker_assessment.derived_quality

        # w_c=0.60 * 1.0 + w_e=0.20 * 1.0 + w_x=0.20 * 1.00 = 1.0
        assert q == pytest.approx(1.0)

    def test_rejected_mission_low_quality(self, engine: QualityEngine) -> None:
        """Unanimously rejected → low quality (consensus=0)."""
        mission = _rejected_mission(tier=RiskTier.R1, evidence_count=2)
        records = _default_trust_records()
        report = engine.assess_mission(mission, records)
        q = report.worker_assessment.derived_quality

        # consensus=0.0, evidence=1.0, complexity=0.90
        # 0.60*0.0 + 0.20*1.0 + 0.20*0.90 = 0.38
        assert q == pytest.approx(0.38)

    def test_derived_quality_clamped_to_unit(self, engine: QualityEngine) -> None:
        """Derived quality should never exceed 1.0."""
        # R3 has complexity 1.10 — even with all components maxed,
        # the weighted sum could exceed 1.0 before clamping
        mission = _approved_mission(tier=RiskTier.R3, evidence_count=3)
        records = _default_trust_records()
        report = engine.assess_mission(mission, records)
        q = report.worker_assessment.derived_quality

        # 0.60*1.0 + 0.20*1.0 + 0.20*1.10 = 1.02 → clamped to 1.0
        assert q == pytest.approx(1.0)
        assert q <= 1.0

    def test_worker_assessment_details(self, engine: QualityEngine) -> None:
        """Assessment includes weights and context in details dict."""
        mission = _approved_mission()
        records = _default_trust_records()
        report = engine.assess_mission(mission, records)
        details = report.worker_assessment.details
        assert "weights" in details
        assert details["weights"]["consensus"] == pytest.approx(0.60)
        assert details["mission_state"] == "approved"


# ===================================================================
# Reviewer alignment
# ===================================================================

class TestReviewerAlignment:
    def test_correct_approve(self, engine: QualityEngine) -> None:
        """Approved mission + APPROVE vote → alignment = 1.0."""
        decisions = [
            ReviewDecision(reviewer_id="rev-1", decision=ReviewDecisionVerdict.APPROVE),
        ]
        mission = _approved_mission(decisions=decisions)
        records = {"rev-1": _trust_record("rev-1")}
        report = engine.assess_mission(mission, records)
        assert report.reviewer_assessments[0].alignment_score == pytest.approx(1.0)

    def test_correct_reject(self, engine: QualityEngine) -> None:
        """Rejected mission + REJECT vote → alignment = 1.0."""
        decisions = [
            ReviewDecision(reviewer_id="rev-1", decision=ReviewDecisionVerdict.REJECT),
        ]
        mission = _rejected_mission(decisions=decisions)
        records = {"rev-1": _trust_record("rev-1")}
        report = engine.assess_mission(mission, records)
        assert report.reviewer_assessments[0].alignment_score == pytest.approx(1.0)

    def test_wrong_reject_dissent_valued(self, engine: QualityEngine) -> None:
        """Approved mission + REJECT vote → 0.3 (dissent partially valued)."""
        decisions = [
            ReviewDecision(reviewer_id="rev-1", decision=ReviewDecisionVerdict.REJECT),
        ]
        mission = _approved_mission(decisions=decisions)
        records = {"rev-1": _trust_record("rev-1")}
        report = engine.assess_mission(mission, records)
        assert report.reviewer_assessments[0].alignment_score == pytest.approx(0.3)

    def test_wrong_approve_rubber_stamp(self, engine: QualityEngine) -> None:
        """Rejected mission + APPROVE vote → 0.2 (rubber-stamping penalized)."""
        decisions = [
            ReviewDecision(reviewer_id="rev-1", decision=ReviewDecisionVerdict.APPROVE),
        ]
        mission = _rejected_mission(decisions=decisions)
        records = {"rev-1": _trust_record("rev-1")}
        report = engine.assess_mission(mission, records)
        assert report.reviewer_assessments[0].alignment_score == pytest.approx(0.2)

    def test_abstain_neutral(self, engine: QualityEngine) -> None:
        """Abstain on any outcome → 0.5."""
        decisions = [
            ReviewDecision(reviewer_id="rev-1", decision=ReviewDecisionVerdict.ABSTAIN),
        ]
        mission = _approved_mission(decisions=decisions)
        records = {"rev-1": _trust_record("rev-1")}
        report = engine.assess_mission(mission, records)
        assert report.reviewer_assessments[0].alignment_score == pytest.approx(0.5)

    def test_dissent_more_valuable_than_rubber_stamp(self, engine: QualityEngine) -> None:
        """wrong_reject (0.3) > wrong_approve (0.2) — constructive challenge valued."""
        decisions_dissent = [
            ReviewDecision(reviewer_id="rev-1", decision=ReviewDecisionVerdict.REJECT),
        ]
        decisions_rubber = [
            ReviewDecision(reviewer_id="rev-1", decision=ReviewDecisionVerdict.APPROVE),
        ]
        mission_approved = _approved_mission(decisions=decisions_dissent)
        mission_rejected = _rejected_mission(decisions=decisions_rubber)
        records = {"rev-1": _trust_record("rev-1")}

        report_dissent = engine.assess_mission(mission_approved, records)
        report_rubber = engine.assess_mission(mission_rejected, records)

        assert (
            report_dissent.reviewer_assessments[0].alignment_score
            > report_rubber.reviewer_assessments[0].alignment_score
        )


# ===================================================================
# Reviewer calibration
# ===================================================================

class TestReviewerCalibration:
    def test_insufficient_history_neutral(self, engine: QualityEngine) -> None:
        """Fewer than min_history assessments → calibration = 0.5."""
        # min_history is 5 per config
        history = [_reviewer_assessment(alignment=1.0) for _ in range(4)]
        mission = _approved_mission(decisions=[
            ReviewDecision(reviewer_id="rev-1", decision=ReviewDecisionVerdict.APPROVE),
        ])
        records = {"rev-1": _trust_record("rev-1")}
        report = engine.assess_mission(
            mission, records, reviewer_histories={"rev-1": history},
        )
        assert report.reviewer_assessments[0].calibration_score == pytest.approx(0.5)

    def test_perfect_calibration(self, engine: QualityEngine) -> None:
        """Mean alignment at 0.5 → calibration = 1.0 (optimal)."""
        # Build history with mean alignment = 0.5
        history = [_reviewer_assessment(alignment=0.5) for _ in range(10)]
        mission = _approved_mission(decisions=[
            ReviewDecision(reviewer_id="rev-1", decision=ReviewDecisionVerdict.APPROVE),
        ])
        records = {"rev-1": _trust_record("rev-1")}
        report = engine.assess_mission(
            mission, records, reviewer_histories={"rev-1": history},
        )
        assert report.reviewer_assessments[0].calibration_score == pytest.approx(1.0)

    def test_extreme_follower_penalized(self, engine: QualityEngine) -> None:
        """Always correct (mean alignment 1.0) → calibration = 0.0.

        This sounds counter-intuitive but catches rubber-stampers who
        always agree with outcomes — they're not exercising independent
        judgment, just following the crowd.
        """
        history = [_reviewer_assessment(alignment=1.0) for _ in range(10)]
        mission = _approved_mission(decisions=[
            ReviewDecision(reviewer_id="rev-1", decision=ReviewDecisionVerdict.APPROVE),
        ])
        records = {"rev-1": _trust_record("rev-1")}
        report = engine.assess_mission(
            mission, records, reviewer_histories={"rev-1": history},
        )
        assert report.reviewer_assessments[0].calibration_score == pytest.approx(0.0)

    def test_extreme_contrarian_penalized(self, engine: QualityEngine) -> None:
        """Always wrong (mean alignment 0.0) → calibration = 0.0."""
        history = [_reviewer_assessment(alignment=0.0) for _ in range(10)]
        mission = _approved_mission(decisions=[
            ReviewDecision(reviewer_id="rev-1", decision=ReviewDecisionVerdict.APPROVE),
        ])
        records = {"rev-1": _trust_record("rev-1")}
        report = engine.assess_mission(
            mission, records, reviewer_histories={"rev-1": history},
        )
        assert report.reviewer_assessments[0].calibration_score == pytest.approx(0.0)

    def test_window_size_respected(self, engine: QualityEngine) -> None:
        """Only the most recent window_size assessments are used.

        Config: calibration_window_size = 20.
        If we have 25 entries with old ones at alignment=1.0 and
        recent ones at 0.5, only recent ones should count.
        """
        old = [_reviewer_assessment(alignment=1.0) for _ in range(5)]
        recent = [_reviewer_assessment(alignment=0.5) for _ in range(20)]
        history = old + recent  # 25 total, last 20 are at 0.5
        mission = _approved_mission(decisions=[
            ReviewDecision(reviewer_id="rev-1", decision=ReviewDecisionVerdict.APPROVE),
        ])
        records = {"rev-1": _trust_record("rev-1")}
        report = engine.assess_mission(
            mission, records, reviewer_histories={"rev-1": history},
        )
        # Window covers only the recent 20 entries (mean 0.5) → calibration ≈ 1.0
        assert report.reviewer_assessments[0].calibration_score == pytest.approx(1.0)


# ===================================================================
# Normative escalation
# ===================================================================

class TestNormativeEscalation:
    def test_objective_never_escalates(self, engine: QualityEngine) -> None:
        """Objective domain → no normative escalation regardless of consensus."""
        decisions = [
            ReviewDecision(reviewer_id="rev-1", decision=ReviewDecisionVerdict.APPROVE),
            ReviewDecision(reviewer_id="rev-2", decision=ReviewDecisionVerdict.REJECT),
        ]
        mission = _approved_mission(
            domain=DomainType.OBJECTIVE, decisions=decisions,
        )
        records = _default_trust_records()
        report = engine.assess_mission(mission, records)
        assert report.normative_escalation_triggered is False

    def test_normative_low_consensus_escalates(self, engine: QualityEngine) -> None:
        """Normative domain + consensus < 0.60 → escalation triggered."""
        decisions = [
            ReviewDecision(reviewer_id="rev-1", decision=ReviewDecisionVerdict.APPROVE),
            ReviewDecision(reviewer_id="rev-2", decision=ReviewDecisionVerdict.REJECT),
        ]
        mission = _approved_mission(
            domain=DomainType.NORMATIVE, decisions=decisions,
        )
        # Equal trust → consensus = 0.5 < 0.60
        records = _default_trust_records()
        report = engine.assess_mission(mission, records)
        assert report.normative_escalation_triggered is True

    def test_normative_high_consensus_no_escalation(self, engine: QualityEngine) -> None:
        """Normative domain + consensus >= 0.60 → no escalation."""
        decisions = [
            ReviewDecision(reviewer_id="rev-1", decision=ReviewDecisionVerdict.APPROVE),
            ReviewDecision(reviewer_id="rev-2", decision=ReviewDecisionVerdict.APPROVE),
        ]
        mission = _approved_mission(
            domain=DomainType.NORMATIVE, decisions=decisions,
        )
        records = _default_trust_records()
        report = engine.assess_mission(mission, records)
        assert report.normative_escalation_triggered is False

    def test_mixed_domain_low_consensus_escalates(self, engine: QualityEngine) -> None:
        """Mixed domain behaves like normative for escalation."""
        decisions = [
            ReviewDecision(reviewer_id="rev-1", decision=ReviewDecisionVerdict.APPROVE),
            ReviewDecision(reviewer_id="rev-2", decision=ReviewDecisionVerdict.REJECT),
        ]
        mission = _approved_mission(
            domain=DomainType.MIXED, decisions=decisions,
        )
        records = _default_trust_records()
        report = engine.assess_mission(mission, records)
        assert report.normative_escalation_triggered is True


# ===================================================================
# Validation
# ===================================================================

class TestValidation:
    def test_non_terminal_mission_raises(self, engine: QualityEngine) -> None:
        """Assessment on a non-terminal mission raises ValueError."""
        mission = Mission(
            mission_id="m-1",
            mission_title="In Progress",
            mission_class=MissionClass.INTERNAL_OPERATIONS_CHANGE,
            risk_tier=RiskTier.R1,
            domain_type=DomainType.OBJECTIVE,
            state=MissionState.IN_REVIEW,
            worker_id="worker-1",
        )
        with pytest.raises(ValueError, match="terminal"):
            engine.assess_mission(mission, {})

    def test_no_worker_raises(self, engine: QualityEngine) -> None:
        """Assessment without worker_id raises ValueError."""
        mission = Mission(
            mission_id="m-1",
            mission_title="No Worker",
            mission_class=MissionClass.INTERNAL_OPERATIONS_CHANGE,
            risk_tier=RiskTier.R1,
            domain_type=DomainType.OBJECTIVE,
            state=MissionState.APPROVED,
            worker_id=None,
        )
        with pytest.raises(ValueError, match="worker_id"):
            engine.assess_mission(mission, {})

    def test_cancelled_mission_raises(self, engine: QualityEngine) -> None:
        """CANCELLED is not a terminal state for quality assessment."""
        mission = Mission(
            mission_id="m-1",
            mission_title="Cancelled",
            mission_class=MissionClass.INTERNAL_OPERATIONS_CHANGE,
            risk_tier=RiskTier.R1,
            domain_type=DomainType.OBJECTIVE,
            state=MissionState.CANCELLED,
            worker_id="worker-1",
        )
        with pytest.raises(ValueError, match="terminal"):
            engine.assess_mission(mission, {})


# ===================================================================
# Report structure
# ===================================================================

class TestReportStructure:
    def test_report_has_all_reviewer_assessments(self, engine: QualityEngine) -> None:
        """Report contains one assessment per review decision."""
        decisions = [
            ReviewDecision(reviewer_id="rev-1", decision=ReviewDecisionVerdict.APPROVE),
            ReviewDecision(reviewer_id="rev-2", decision=ReviewDecisionVerdict.REJECT),
            ReviewDecision(reviewer_id="rev-3", decision=ReviewDecisionVerdict.ABSTAIN),
        ]
        mission = _approved_mission(decisions=decisions)
        records = {
            "rev-1": _trust_record("rev-1"),
            "rev-2": _trust_record("rev-2"),
            "rev-3": _trust_record("rev-3"),
        }
        report = engine.assess_mission(mission, records)
        assert len(report.reviewer_assessments) == 3
        reviewer_ids = {a.reviewer_id for a in report.reviewer_assessments}
        assert reviewer_ids == {"rev-1", "rev-2", "rev-3"}

    def test_report_mission_id_matches(self, engine: QualityEngine) -> None:
        """Report mission_id matches the input mission."""
        mission = _approved_mission()
        records = _default_trust_records()
        report = engine.assess_mission(mission, records)
        assert report.mission_id == "mission-001"
        assert report.worker_assessment.mission_id == "mission-001"
