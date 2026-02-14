"""Quality assessment models — results of deriving quality from mission outcomes.

Quality is the bridge between work and trust. When a mission completes,
these models capture the derived quality scores for workers and reviewers.
The scores flow into the trust engine as measured inputs, replacing the
god-parameter pattern where callers supply arbitrary quality values.

Constitutional invariant: "Quality dominates trust (w_Q >= 0.70)."
This module ensures quality is actually measured, not just declared.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class WorkerQualityAssessment:
    """Quality assessment for the worker who completed a mission.

    Derived from review consensus, evidence thoroughness, and mission
    complexity. The derived_quality value feeds directly into
    TrustEngine.apply_update() as the quality dimension.
    """
    mission_id: str
    worker_id: str
    consensus_score: float      # 0.0-1.0: weighted approval ratio
    evidence_score: float       # 0.0-1.0: evidence vs tier expectation
    complexity_factor: float    # tier multiplier (R0=0.80 .. R3=1.10)
    derived_quality: float      # final Q for trust update, clamped [0,1]
    assessment_utc: datetime
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ReviewerQualityAssessment:
    """Quality assessment for a single reviewer on a single mission.

    Alignment measures whether the reviewer's vote matched the final
    outcome. Calibration measures historical accuracy — are they too
    lenient (rubber-stamper) or too strict (blocker)?

    Dissent has partial value: rejecting an ultimately-approved mission
    scores higher (0.3) than approving an ultimately-rejected one (0.2),
    because constructive challenge is valuable in governance.
    """
    reviewer_id: str
    mission_id: str
    alignment_score: float      # 0.0-1.0: vote vs outcome match
    calibration_score: float    # 0.0-1.0: historical accuracy
    derived_quality: float      # final Q for reviewer's trust update
    assessment_utc: datetime
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MissionQualityReport:
    """Complete quality assessment output for a completed mission.

    Contains worker assessment, all reviewer assessments, and whether
    normative escalation was triggered (blocking auto trust update).
    """
    mission_id: str
    worker_assessment: WorkerQualityAssessment
    reviewer_assessments: list[ReviewerQualityAssessment]
    normative_escalation_triggered: bool
    assessment_utc: datetime
