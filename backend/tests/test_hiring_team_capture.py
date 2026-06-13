"""Tests for the LinkedIn 'Meet the hiring team' capture ingest + ranking."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.people import hiring_team_capture as htc

pytestmark = pytest.mark.asyncio


def test_classify_member_from_label_and_headline():
    f = htc._classify_member
    assert f("", "Job poster · Recruiter") == "recruiter"
    assert f("Senior Technical Recruiter", "Job poster") == "recruiter"
    assert f("Engineering Manager", "Hiring manager") == "hiring_manager"
    assert f("Director of Design", "") == "hiring_manager"
    # hiring-team panel default is a hiring contact (recruiter), never a peer
    assert f("Works on cool products", "") == "recruiter"


def test_member_to_candidate_shape_and_verified():
    cand = htc._member_to_candidate(
        {"name": "Jane Doe", "headline": "Technical Recruiter", "role_label": "Job poster", "profile_url": "https://www.linkedin.com/in/janedoe"},
        "Acme",
        "Staff Engineer",
    )
    assert cand["bucket"] == "recruiter"
    data = cand["data"]
    assert data["source"] == "linkedin_hiring_team"
    assert data["_hiring_team_capture"] is True
    assert data["_employment_status"] == "current"
    assert data["profile_data"]["company_match_confidence"] == "verified"
    assert data["profile_data"]["current_company_verified"] is True
    assert "Staff Engineer" in data["snippet"]

    # single-token / empty names rejected
    assert htc._member_to_candidate({"name": "Madonna"}, "Acme", None) is None
    assert htc._member_to_candidate({"name": ""}, "Acme", None) is None


async def test_ingest_stores_and_classifies():
    user_id = uuid.uuid4()
    company = MagicMock(id=uuid.uuid4(), domain=None)
    db = MagicMock()
    db.commit = AsyncMock()

    members = [
        {"name": "Jane Doe", "headline": "Technical Recruiter", "role_label": "Job poster", "profile_url": "https://linkedin.com/in/jane"},
        {"name": "Sam Lead", "headline": "Engineering Manager", "role_label": "Hiring manager", "profile_url": "https://linkedin.com/in/sam"},
    ]

    stored_people = []

    async def fake_store(db_, uid, comp, data, bucket):
        person = MagicMock(full_name=data["full_name"], person_type=bucket)
        stored_people.append((bucket, data))
        return person

    with (
        patch.object(htc, "get_or_create_company", new=AsyncMock(return_value=company)),
        patch.object(htc, "_store_person", new=AsyncMock(side_effect=fake_store)),
        patch("app.services.known_people_service.write_candidates_to_cache", new=AsyncMock(return_value=2)),
    ):
        result = await htc.ingest_hiring_team_capture(
            db, user_id, company_name="Acme", members=members, job_title="Staff Engineer"
        )

    assert result["stored"] == 2
    assert result["recruiters"] == 1
    assert result["hiring_managers"] == 1
    buckets = {b for b, _ in stored_people}
    assert buckets == {"recruiter", "hiring_manager"}
    db.commit.assert_awaited()


async def test_ingest_empty_is_noop():
    db = MagicMock()
    result = await htc.ingest_hiring_team_capture(db, uuid.uuid4(), company_name="Acme", members=[])
    assert result["stored"] == 0
    result = await htc.ingest_hiring_team_capture(db, uuid.uuid4(), company_name="", members=[{"name": "X Y"}])
    assert result["stored"] == 0


def test_hiring_team_rank_is_top_signal_in_buckets():
    from app.services.people.candidates import _prepare_candidates
    from app.utils.job_context import JobContext

    ctx = JobContext(department="engineering", team_keywords=["payments"],
                     manager_titles=["Engineering Manager"], seniority="mid")

    captured_recruiter = {
        "full_name": "Captured Recruiter", "title": "Recruiter", "source": "linkedin_hiring_team",
        "snippet": "Named on Acme's hiring team", "_hiring_team_capture": True,
        "_employment_status": "current",
        "profile_data": {"company_match_confidence": "verified"},
    }
    other_recruiters = [
        {"full_name": f"Other R{i}", "title": "Senior Recruiter", "source": "brave_search",
         "snippet": "Recruiter at Acme", "_employment_status": "current",
         "profile_data": {"company_match_confidence": "strong_signal"}}
        for i in range(3)
    ]
    ranked = _prepare_candidates(
        other_recruiters[:2] + [captured_recruiter] + other_recruiters[2:],
        company_name="Acme", public_identity_slugs=["acme"], bucket="recruiters", context=ctx, limit=5,
    )
    assert ranked[0]["full_name"] == "Captured Recruiter"

    captured_hm = {
        "full_name": "Captured HM", "title": "Engineering Manager", "source": "linkedin_hiring_team",
        "snippet": "Named on Acme's hiring team", "_hiring_team_capture": True,
        "_employment_status": "current",
        "profile_data": {"company_match_confidence": "verified"},
    }
    gh_hm = {
        "full_name": "GitHub Lead", "title": "Engineering Manager", "source": "github_team",
        "snippet": "team leader at Acme", "_github_team_member": True, "_employment_status": "current",
        "profile_data": {"company_match_confidence": "strong_signal", "github_team": True},
    }
    ranked = _prepare_candidates(
        [gh_hm, captured_hm], company_name="Acme", public_identity_slugs=["acme"],
        bucket="hiring_managers", context=ctx, limit=5,
    )
    # hiring-team capture (literal req owner) outranks even the github-team lead
    assert ranked[0]["full_name"] == "Captured HM"
