"""Unit tests for protected leave data models.

Tests LeaveCategory, LeaveState, AdjudicationVerdict,
LeaveAdjudication, LeaveRecord, and the CATEGORY_REQUIRED_DOMAINS mapping.
"""

import pytest
from datetime import datetime, timezone

from genesis.models.leave import (
    AdjudicationVerdict,
    CATEGORY_REQUIRED_DOMAINS,
    LeaveAdjudication,
    LeaveCategory,
    LeaveRecord,
    LeaveState,
)


# ===================================================================
# LeaveCategory
# ===================================================================

class TestLeaveCategory:
    def test_eight_categories_exist(self) -> None:
        """All eight protected categories must be present (including death)."""
        expected = {
            "illness", "bereavement", "disability", "mental_health",
            "caregiver", "pregnancy", "child_care", "death",
        }
        actual = {c.value for c in LeaveCategory}
        assert actual == expected

    def test_illness_value(self) -> None:
        assert LeaveCategory.ILLNESS.value == "illness"

    def test_bereavement_value(self) -> None:
        assert LeaveCategory.BEREAVEMENT.value == "bereavement"

    def test_disability_value(self) -> None:
        assert LeaveCategory.DISABILITY.value == "disability"

    def test_mental_health_value(self) -> None:
        assert LeaveCategory.MENTAL_HEALTH.value == "mental_health"

    def test_caregiver_value(self) -> None:
        assert LeaveCategory.CAREGIVER.value == "caregiver"

    def test_pregnancy_value(self) -> None:
        assert LeaveCategory.PREGNANCY.value == "pregnancy"

    def test_child_care_value(self) -> None:
        assert LeaveCategory.CHILD_CARE.value == "child_care"

    def test_category_from_string(self) -> None:
        assert LeaveCategory("pregnancy") == LeaveCategory.PREGNANCY

    def test_invalid_category_raises(self) -> None:
        with pytest.raises(ValueError):
            LeaveCategory("vacation")


# ===================================================================
# CATEGORY_REQUIRED_DOMAINS mapping
# ===================================================================

class TestCategoryRequiredDomains:
    def test_all_categories_have_domains(self) -> None:
        """Every category must map to at least one required domain."""
        for cat in LeaveCategory:
            assert cat.value in CATEGORY_REQUIRED_DOMAINS, (
                f"Missing domain mapping for {cat.value}"
            )
            assert len(CATEGORY_REQUIRED_DOMAINS[cat.value]) > 0

    def test_illness_requires_healthcare(self) -> None:
        assert "healthcare" in CATEGORY_REQUIRED_DOMAINS["illness"]

    def test_bereavement_domains(self) -> None:
        domains = CATEGORY_REQUIRED_DOMAINS["bereavement"]
        assert "social_services" in domains
        assert "mental_health" in domains

    def test_disability_domains(self) -> None:
        domains = CATEGORY_REQUIRED_DOMAINS["disability"]
        assert "healthcare" in domains
        assert "social_services" in domains

    def test_mental_health_domains(self) -> None:
        domains = CATEGORY_REQUIRED_DOMAINS["mental_health"]
        assert "mental_health" in domains
        assert "healthcare" in domains

    def test_caregiver_requires_social_services(self) -> None:
        assert "social_services" in CATEGORY_REQUIRED_DOMAINS["caregiver"]

    def test_pregnancy_requires_healthcare(self) -> None:
        assert "healthcare" in CATEGORY_REQUIRED_DOMAINS["pregnancy"]

    def test_child_care_requires_social_services(self) -> None:
        assert "social_services" in CATEGORY_REQUIRED_DOMAINS["child_care"]


# ===================================================================
# LeaveState
# ===================================================================

class TestLeaveState:
    def test_six_states_exist(self) -> None:
        expected = {"pending", "approved", "denied", "active", "returned", "memorialised"}
        actual = {s.value for s in LeaveState}
        assert actual == expected

    def test_pending_is_default(self) -> None:
        record = LeaveRecord(leave_id="L1", actor_id="A1", category=LeaveCategory.ILLNESS)
        assert record.state == LeaveState.PENDING


# ===================================================================
# AdjudicationVerdict
# ===================================================================

class TestAdjudicationVerdict:
    def test_three_verdicts(self) -> None:
        expected = {"approve", "deny", "abstain"}
        actual = {v.value for v in AdjudicationVerdict}
        assert actual == expected


# ===================================================================
# LeaveAdjudication
# ===================================================================

class TestLeaveAdjudication:
    def test_creation(self) -> None:
        now = datetime.now(timezone.utc)
        adj = LeaveAdjudication(
            adjudicator_id="DOC-001",
            verdict=AdjudicationVerdict.APPROVE,
            domain_qualified="healthcare",
            trust_score_at_decision=0.75,
            notes="Verified documentation",
            timestamp_utc=now,
        )
        assert adj.adjudicator_id == "DOC-001"
        assert adj.verdict == AdjudicationVerdict.APPROVE
        assert adj.domain_qualified == "healthcare"
        assert adj.trust_score_at_decision == 0.75
        assert adj.notes == "Verified documentation"
        assert adj.timestamp_utc == now

    def test_frozen(self) -> None:
        """LeaveAdjudication is immutable (frozen dataclass)."""
        adj = LeaveAdjudication(
            adjudicator_id="DOC-001",
            verdict=AdjudicationVerdict.APPROVE,
            domain_qualified="healthcare",
            trust_score_at_decision=0.75,
        )
        with pytest.raises(AttributeError):
            adj.verdict = AdjudicationVerdict.DENY  # type: ignore

    def test_default_notes_empty(self) -> None:
        adj = LeaveAdjudication(
            adjudicator_id="DOC-001",
            verdict=AdjudicationVerdict.DENY,
            domain_qualified="mental_health",
            trust_score_at_decision=0.60,
        )
        assert adj.notes == ""
        assert adj.timestamp_utc is None


# ===================================================================
# LeaveRecord
# ===================================================================

class TestLeaveRecord:
    def _make_record(self, **kwargs) -> LeaveRecord:
        defaults = {
            "leave_id": "LEAVE-000001",
            "actor_id": "ACTOR-001",
            "category": LeaveCategory.ILLNESS,
        }
        defaults.update(kwargs)
        return LeaveRecord(**defaults)

    def test_default_state_is_pending(self) -> None:
        record = self._make_record()
        assert record.state == LeaveState.PENDING

    def test_approve_count_empty(self) -> None:
        record = self._make_record()
        assert record.approve_count() == 0

    def test_deny_count_empty(self) -> None:
        record = self._make_record()
        assert record.deny_count() == 0

    def test_abstain_count_empty(self) -> None:
        record = self._make_record()
        assert record.abstain_count() == 0

    def test_has_quorum_false_with_no_votes(self) -> None:
        record = self._make_record()
        assert record.has_quorum(3) is False

    def test_approve_count_with_votes(self) -> None:
        record = self._make_record()
        record.adjudications = [
            LeaveAdjudication("A1", AdjudicationVerdict.APPROVE, "healthcare", 0.5),
            LeaveAdjudication("A2", AdjudicationVerdict.APPROVE, "healthcare", 0.6),
            LeaveAdjudication("A3", AdjudicationVerdict.DENY, "healthcare", 0.7),
        ]
        assert record.approve_count() == 2
        assert record.deny_count() == 1
        assert record.abstain_count() == 0

    def test_has_quorum_with_three_non_abstain(self) -> None:
        record = self._make_record()
        record.adjudications = [
            LeaveAdjudication("A1", AdjudicationVerdict.APPROVE, "healthcare", 0.5),
            LeaveAdjudication("A2", AdjudicationVerdict.DENY, "healthcare", 0.6),
            LeaveAdjudication("A3", AdjudicationVerdict.APPROVE, "healthcare", 0.7),
        ]
        assert record.has_quorum(3) is True

    def test_abstentions_dont_count_toward_quorum(self) -> None:
        record = self._make_record()
        record.adjudications = [
            LeaveAdjudication("A1", AdjudicationVerdict.APPROVE, "healthcare", 0.5),
            LeaveAdjudication("A2", AdjudicationVerdict.ABSTAIN, "healthcare", 0.6),
            LeaveAdjudication("A3", AdjudicationVerdict.APPROVE, "healthcare", 0.7),
        ]
        assert record.has_quorum(3) is False  # Only 2 non-abstain

    def test_freeze_fields_none_by_default(self) -> None:
        record = self._make_record()
        assert record.trust_score_at_freeze is None
        assert record.last_active_utc_at_freeze is None
        assert record.domain_scores_at_freeze == {}

    def test_duration_fields_none_by_default(self) -> None:
        record = self._make_record()
        assert record.granted_duration_days is None
        assert record.expires_utc is None

    def test_timestamp_fields_none_by_default(self) -> None:
        record = self._make_record()
        assert record.requested_utc is None
        assert record.approved_utc is None
        assert record.denied_utc is None
        assert record.returned_utc is None

    def test_reason_summary_default_empty(self) -> None:
        record = self._make_record()
        assert record.reason_summary == ""

    def test_pregnancy_category(self) -> None:
        record = self._make_record(category=LeaveCategory.PREGNANCY)
        assert record.category == LeaveCategory.PREGNANCY

    def test_child_care_category(self) -> None:
        record = self._make_record(category=LeaveCategory.CHILD_CARE)
        assert record.category == LeaveCategory.CHILD_CARE

    def test_mixed_verdicts_count(self) -> None:
        record = self._make_record()
        record.adjudications = [
            LeaveAdjudication("A1", AdjudicationVerdict.APPROVE, "healthcare", 0.5),
            LeaveAdjudication("A2", AdjudicationVerdict.DENY, "healthcare", 0.6),
            LeaveAdjudication("A3", AdjudicationVerdict.ABSTAIN, "healthcare", 0.7),
            LeaveAdjudication("A4", AdjudicationVerdict.APPROVE, "healthcare", 0.8),
        ]
        assert record.approve_count() == 2
        assert record.deny_count() == 1
        assert record.abstain_count() == 1
