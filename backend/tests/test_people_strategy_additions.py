"""Tests for the people-discovery strategy additions.

Covers: named posting contacts, the req-poster posts-scope search, affinity
signals, outcome-driven priors, and the contact feedback eviction path.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.services.people.affinity import affinity_rank, annotate_affinity, compute_affinity
from app.services.people.outcome_priors import outcome_prior_rank, stamp_outcome_priors
from app.utils.job_context import _extract_posting_contacts

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Named posting contacts
# ---------------------------------------------------------------------------

def test_posting_contact_extraction_named_and_generic():
    desc = (
        "Questions? Contact Jane Doe at jane.doe@acme.com. "
        "You can also apply via careers@acme.com."
    )
    contacts = _extract_posting_contacts(desc)
    by_email = {c["email"]: c for c in contacts}
    assert by_email["jane.doe@acme.com"]["generic"] is False
    assert by_email["jane.doe@acme.com"]["name"] == "Jane Doe"
    assert by_email["careers@acme.com"]["generic"] is True
    assert _extract_posting_contacts("No contacts here.") == []
    assert _extract_posting_contacts(None) == []


def test_posting_contact_candidates_skip_generic_and_rank_first():
    from app.services.people.ranking import _candidate_sort_key
    from app.services.people.service import _posting_contact_candidates

    job = SimpleNamespace(company_name="Acme", title="Platform Engineer")
    context = SimpleNamespace(
        posting_contacts=[
            {"name": "Jane Doe", "email": "jane.doe@acme.com", "generic": False},
            {"name": None, "email": "jobs@acme.com", "generic": True},
        ]
    )
    candidates = _posting_contact_candidates(job, context)
    assert len(candidates) == 1
    contact = candidates[0]
    assert contact["full_name"] == "Jane Doe"
    assert contact["email_source"] == "job_posting"
    assert contact["profile_data"]["company_match_confidence"] == "verified"

    ordinary = {
        "full_name": "Some Recruiter",
        "title": "Technical Recruiter",
        "_actively_hiring": True,
        "profile_data": {},
    }
    order = sorted(
        [ordinary, contact],
        key=lambda c: _candidate_sort_key(c, bucket="recruiters", context=None),
    )
    assert order[0]["full_name"] == "Jane Doe"


async def test_req_poster_scope_switches_to_posts():
    from app.clients import searxng_search_client

    captured = {}

    async def fake_run(query, limit):
        captured["query"] = query
        return []

    with patch.object(searxng_search_client, "_run_searxng_query", new=AsyncMock(side_effect=fake_run)):
        await searxng_search_client.search_hiring_team(
            "Acme", "Platform Engineer", site_scope="posts"
        )
    assert "site:linkedin.com/posts" in captured["query"]
    assert '"Platform Engineer"' in captured["query"]

    with patch.object(searxng_search_client, "_run_searxng_query", new=AsyncMock(side_effect=fake_run)):
        await searxng_search_client.search_hiring_team("Acme", "Platform Engineer")
    assert "site:linkedin.com/jobs" in captured["query"]


# ---------------------------------------------------------------------------
# Affinity
# ---------------------------------------------------------------------------

def _resume():
    return {
        "education": [{"school": "University of Waterloo"}],
        "experience": [{"company": "Shopify"}, {"company": "Acme"}],
    }


def test_affinity_matches_school_and_past_company():
    school_candidate = {
        "title": "Recruiter",
        "snippet": "Recruiter at Acme. University of Waterloo alum.",
        "profile_data": {},
    }
    affinity = compute_affinity(_resume(), school_candidate, target_company="Acme")
    assert affinity == {"type": "school", "name": "University Of Waterloo"}

    company_candidate = {
        "title": "Engineering Manager",
        "snippet": "Engineering Manager at Acme.",
        "profile_data": {"experiences": [{"company": "Shopify"}]},
    }
    affinity = compute_affinity(_resume(), company_candidate, target_company="Acme")
    assert affinity == {"type": "past_company", "name": "Shopify"}


def test_affinity_never_counts_target_company_and_ranks_late():
    target_only = {
        "title": "Engineer",
        "snippet": "Engineer at Acme.",
        "profile_data": {"experiences": [{"company": "Acme"}]},
    }
    assert compute_affinity(_resume(), target_only, target_company="Acme") is None

    matched = {"title": "Engineer", "snippet": "Shopify alum", "profile_data": {"experiences": [{"company": "Shopify"}]}}
    unmatched = {"title": "Engineer", "snippet": "", "profile_data": {}}
    n = annotate_affinity([matched, unmatched], _resume(), target_company="Acme")
    assert n == 1
    assert affinity_rank(matched) == 0
    assert affinity_rank(unmatched) == 1
    assert matched["profile_data"]["affinity"]["type"] == "past_company"


# ---------------------------------------------------------------------------
# Outcome priors
# ---------------------------------------------------------------------------

def test_outcome_priors_favor_above_average_archetypes():
    priors = {
        ("recruiter", "ic"): 0.5,
        ("recruiter", "director_plus"): 0.1,
    }
    ic = {"title": "Recruiter", "_org_level": "ic"}
    director = {"title": "Director of Talent", "_org_level": "director_plus"}
    stamp_outcome_priors([ic, director], priors, bucket="recruiters")
    assert outcome_prior_rank(ic) == 0
    assert outcome_prior_rank(director) == 1


def test_outcome_priors_neutral_without_data():
    candidate = {"title": "Recruiter", "_org_level": "ic"}
    stamp_outcome_priors([candidate], {}, bucket="recruiters")
    assert outcome_prior_rank(candidate) == 1
    stamp_outcome_priors([candidate], {("peer", "ic"): 0.9}, bucket="recruiters")
    assert outcome_prior_rank(candidate) == 1


# ---------------------------------------------------------------------------
# Known-people eviction on feedback
# ---------------------------------------------------------------------------

async def test_expire_known_person_marks_rows():
    from app.services.known_people_service import expire_known_person

    row = SimpleNamespace(verification_status="fresh")
    db = AsyncMock()
    scalars = SimpleNamespace(all=lambda: [row])
    db.execute = AsyncMock(return_value=SimpleNamespace(scalars=lambda: scalars))
    db.commit = AsyncMock()

    evicted = await expire_known_person(db, company_name="Acme", full_name="Jane Doe")
    assert evicted is True
    assert row.verification_status == "expired"
    db.commit.assert_awaited()

    assert await expire_known_person(db, company_name="Acme", full_name=None) is False
