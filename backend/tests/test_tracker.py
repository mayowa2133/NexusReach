"""Tests for the application tracker (interview rounds + offer tracking)."""

from __future__ import annotations

import pytest

from app.schemas.jobs import (
    InterviewRound,
    InterviewRoundsUpdate,
    OfferDetails,
    OfferDetailsUpdate,
    JobStageUpdate,
    VALID_STAGES,
    VALID_INTERVIEW_TYPES,
    VALID_OFFER_STATUSES,
)


# ---------------------------------------------------------------------------
# Stage validation
# ---------------------------------------------------------------------------


class TestStages:
    def test_valid_stages_includes_new_stages(self):
        assert "accepted" in VALID_STAGES
        assert "rejected" in VALID_STAGES
        assert "withdrawn" in VALID_STAGES

    def test_all_original_stages_present(self):
        for stage in ["discovered", "interested", "researching", "networking",
                       "applied", "interviewing", "offer"]:
            assert stage in VALID_STAGES

    def test_stage_update_schema(self):
        update = JobStageUpdate(stage="accepted", notes="Got the offer!")
        assert update.stage == "accepted"
        assert update.notes == "Got the offer!"


# ---------------------------------------------------------------------------
# Interview round schemas
# ---------------------------------------------------------------------------


class TestInterviewRounds:
    def test_basic_round(self):
        r = InterviewRound(
            round=1,
            interview_type="phone_screen",
            completed=False,
        )
        assert r.round == 1
        assert r.interview_type == "phone_screen"
        assert r.completed is False

    def test_full_round(self):
        r = InterviewRound(
            round=2,
            interview_type="technical",
            scheduled_at="2026-04-10T14:00:00Z",
            completed=True,
            interviewer="Jane Smith",
            notes="Went well, discussed system design",
        )
        assert r.completed is True
        assert r.interviewer == "Jane Smith"

    def test_round_number_must_be_positive(self):
        with pytest.raises(Exception):
            InterviewRound(round=0, interview_type="technical")

    def test_update_schema(self):
        update = InterviewRoundsUpdate(
            interview_rounds=[
                InterviewRound(round=1, interview_type="phone_screen"),
                InterviewRound(round=2, interview_type="onsite", completed=True),
            ]
        )
        assert len(update.interview_rounds) == 2

    def test_valid_interview_types_set(self):
        for t in ["phone_screen", "technical", "behavioral", "system_design",
                   "onsite", "hiring_manager", "final", "take_home", "other"]:
            assert t in VALID_INTERVIEW_TYPES


# ---------------------------------------------------------------------------
# Offer details schemas
# ---------------------------------------------------------------------------


class TestOfferDetails:
    def test_basic_offer(self):
        offer = OfferDetails(salary=150000, status="pending")
        assert offer.salary == 150000
        assert offer.salary_currency == "USD"
        assert offer.status == "pending"

    def test_full_offer(self):
        offer = OfferDetails(
            salary=200000,
            salary_currency="USD",
            equity="50,000 RSUs / 4yr",
            bonus=30000,
            deadline="2026-04-15",
            status="accepted",
            start_date="2026-06-01",
            notes="Negotiated from 180k",
        )
        assert offer.equity == "50,000 RSUs / 4yr"
        assert offer.bonus == 30000
        assert offer.status == "accepted"

    def test_update_schema(self):
        update = OfferDetailsUpdate(
            offer_details=OfferDetails(salary=120000, status="pending")
        )
        assert update.offer_details.salary == 120000

    def test_valid_offer_statuses(self):
        for s in ["pending", "accepted", "declined", "expired"]:
            assert s in VALID_OFFER_STATUSES

    def test_default_currency_is_usd(self):
        offer = OfferDetails()
        assert offer.salary_currency == "USD"

    def test_default_status_is_pending(self):
        offer = OfferDetails()
        assert offer.status == "pending"


# ---------------------------------------------------------------------------
# Serialization round-trip
# ---------------------------------------------------------------------------


class TestSerialization:
    def test_interview_round_to_dict(self):
        r = InterviewRound(round=1, interview_type="technical", completed=True)
        d = r.model_dump()
        assert d["round"] == 1
        assert d["completed"] is True

    def test_offer_details_to_dict(self):
        offer = OfferDetails(salary=100000, bonus=10000)
        d = offer.model_dump()
        assert d["salary"] == 100000
        assert d["bonus"] == 10000
        assert d["salary_currency"] == "USD"
