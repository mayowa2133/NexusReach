"""Tests for the job/people discovery accuracy fixes.

Covers: bucket-aware known-people cache short-circuit, occupation hint
threading through discover, discover coverage (limit/sources/locations),
reporting-line mining, the HM-focused Org gate, and the LLM title tie-break.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.people import candidates as people_candidates
from app.services.people import title_llm
from app.services.people.classify import _classify_person_with_confidence
from app.utils.job_context import _extract_reporting_line_titles

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Fix 1 - bucket-aware cache short-circuit
# ---------------------------------------------------------------------------

def test_cached_title_matches_requires_relevant_title():
    match = people_candidates._cached_title_matches
    assert match("Senior Technical Recruiter", ["Recruiter"]) is True
    assert match("Engineering Manager, Payments", ["Engineering Manager"]) is True
    assert match("Senior Technical Recruiter", ["Engineering Manager"]) is False
    assert match(None, ["Recruiter"]) is False
    # empty request list = company-level search, everything qualifies
    assert match("Anything", []) is True


async def test_cache_short_circuit_is_bucket_aware():
    """Cached recruiters must not suppress a live hiring-manager search."""
    cached_recruiters = [
        {"full_name": f"R{i}", "title": "Technical Recruiter"} for i in range(3)
    ]
    db = MagicMock()

    with (
        patch(
            "app.services.known_people_service.lookup_known_people",
            new=AsyncMock(return_value=cached_recruiters),
        ),
        patch.object(
            people_candidates.apollo_client,
            "search_people",
            new=AsyncMock(return_value=[]),
        ) as mock_apollo,
        patch.object(
            people_candidates.search_router_client,
            "search_people",
            new=AsyncMock(return_value=[]),
        ),
        patch.object(
            people_candidates.search_router_client,
            "search_public_people",
            new=AsyncMock(return_value=[]),
        ),
    ):
        results = await people_candidates._search_candidates(
            "Acme",
            titles=["Engineering Manager"],
            db=db,
            limit=5,
            min_results=2,
        )

    # live search ran because no cached row matched the requested bucket;
    # cached rows may still join the pool as supplements (bucketed later)
    mock_apollo.assert_awaited()
    assert isinstance(results, list)


async def test_cache_short_circuit_fires_on_relevant_rows():
    cached_managers = [
        {"full_name": f"M{i}", "title": "Engineering Manager"} for i in range(3)
    ]
    db = MagicMock()

    with (
        patch(
            "app.services.known_people_service.lookup_known_people",
            new=AsyncMock(return_value=cached_managers),
        ),
        patch.object(
            people_candidates.apollo_client,
            "search_people",
            new=AsyncMock(return_value=[]),
        ) as mock_apollo,
    ):
        results = await people_candidates._search_candidates(
            "Acme",
            titles=["Engineering Manager"],
            db=db,
            limit=5,
            min_results=2,
        )

    mock_apollo.assert_not_awaited()
    assert len(results) == 3


# ---------------------------------------------------------------------------
# Fix 2 - occupation hint threading
# ---------------------------------------------------------------------------

def test_occupation_fallback_only_when_classification_empty():
    from app.services.occupation_taxonomy import occupation_tags_for_job

    # clear title: classification wins, fallback ignored
    tags = occupation_tags_for_job(
        title="Senior Software Engineer",
        fallback_keys=["sales"],
    )
    assert tags == ["occupation:software_engineering"]

    # opaque title: fallback hint applies
    tags = occupation_tags_for_job(title="Associate II", fallback_keys=["sales"])
    assert tags == ["occupation:sales"]

    # explicit source hint beats everything
    tags = occupation_tags_for_job(
        title="Associate II",
        explicit_keys=["healthcare"],
        fallback_keys=["sales"],
    )
    assert tags == ["occupation:healthcare"]


def test_infer_occupation_tags_consumes_hint():
    from app.services.job_service import _infer_occupation_tags_for_job

    data = {"title": "Associate II", "_occupation_hint": "sales", "tags": []}
    _infer_occupation_tags_for_job(data)
    assert "occupation:sales" in (data.get("tags") or [])
    assert "_occupation_hint" not in data


# ---------------------------------------------------------------------------
# Fix 4 - discover coverage: limit, sources, locations, hint
# ---------------------------------------------------------------------------

async def test_discover_fans_out_locations_and_passes_hint():
    from app.services import job_service

    profile = MagicMock()
    profile.target_occupations = ["sales"]
    profile.target_roles = None
    profile.target_locations = ["Toronto, ON", "New York, NY", "London"]

    db = MagicMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = profile
    db.execute = AsyncMock(return_value=result)

    with (
        patch.object(job_service, "search_jobs", new=AsyncMock(return_value=[])) as mock_search,
        patch.object(
            job_service.newgrad_jobs_client,
            "search_newgrad_jobs",
            new=AsyncMock(return_value=[]),
        ),
        patch.object(job_service, "_store_raw_jobs", new=AsyncMock(return_value=[])),
        patch.object(job_service, "_discover_ats_boards", new=AsyncMock(return_value=0)),
    ):
        await job_service.discover_jobs(db, uuid.uuid4())

    assert mock_search.await_count > 0
    seen_locations = set()
    for call in mock_search.await_args_list:
        kwargs = call.kwargs
        assert kwargs["limit"] == job_service.DISCOVER_LIMIT_PER_SOURCE
        assert kwargs["occupation_hint"] == "sales"
        assert "jobicy" in kwargs["sources"] and "simplify" in kwargs["sources"]
        seen_locations.add(kwargs["location"])
    # base (None) plus the first two target locations - capped fan-out
    assert None in seen_locations
    assert "Toronto, ON" in seen_locations
    assert "New York, NY" in seen_locations
    assert "London" not in seen_locations


# ---------------------------------------------------------------------------
# Fix 5 - reporting-line mining + HM org gate
# ---------------------------------------------------------------------------

def test_reporting_line_titles_extracted_and_prioritized():
    desc = (
        "Join our payments team. You will report to the Director of Data "
        "Engineering and collaborate with peers. This role reports directly "
        "to our VP of Engineering for strategy."
    )
    titles = _extract_reporting_line_titles(desc)
    assert "Director of Data Engineering" in titles
    assert any("VP of Engineering" in t for t in titles)


def test_reporting_line_ignores_non_title_phrases():
    assert _extract_reporting_line_titles("Report to the office on Monday.") == []
    assert _extract_reporting_line_titles(None) == []


def test_theorg_gate_expands_for_hm_with_team_keywords():
    gate = people_candidates._should_expand_with_theorg
    # Engineering context: isolates the team-keyword clause from the
    # non-engineering always-expand clause.
    context = MagicMock()
    context.team_keywords = ["payments"]
    context.occupation_keys = ["software_engineering"]
    context.department = "engineering"

    full_buckets = {"recruiters": 3, "hiring_managers": 3, "peers": 3}
    # buckets are at target, but team keywords justify HM cross-check
    assert gate("Stripe", full_buckets, context=context, target_count_per_bucket=3) is True

    # HM bucket already overflowing - no need
    overflowing = {"recruiters": 3, "hiring_managers": 5, "peers": 3}
    assert gate("Stripe", overflowing, context=context, target_count_per_bucket=3) is False

    # no team keywords and full buckets - unchanged old behavior
    context.team_keywords = []
    assert gate("Stripe", full_buckets, context=context, target_count_per_bucket=3) is False


# ---------------------------------------------------------------------------
# Fix 6 - LLM title tie-break
# ---------------------------------------------------------------------------

def test_classifier_confidence_flags_ambiguous_tail():
    assert _classify_person_with_confidence("Software Engineer") == ("peer", True)
    assert _classify_person_with_confidence("Technical Recruiter") == ("recruiter", True)
    assert _classify_person_with_confidence("Director of Engineering") == (
        "hiring_manager",
        True,
    )
    bucket, confident = _classify_person_with_confidence("Solutions Catalyst")
    assert confident is False
    assert bucket == "peer"


async def test_resolve_ambiguous_titles_uses_cache_then_llm():
    cache: dict[str, str] = {title_llm._cache_key("partner"): "hiring_manager"}

    async def fake_get(key):
        return cache.get(key)

    written = {}

    async def fake_set(key, payload, *, ttl_seconds=None):
        written[key] = payload

    with (
        patch.object(title_llm.search_cache_client, "get_json", new=AsyncMock(side_effect=fake_get)),
        patch.object(title_llm.search_cache_client, "set_json", new=AsyncMock(side_effect=fake_set)),
        patch.object(
            title_llm.llm_client,
            "generate_message",
            new=AsyncMock(return_value={"draft": '{"talent sherpa": "recruiter"}'}),
        ) as mock_llm,
    ):
        resolved = await title_llm.resolve_ambiguous_titles(["Partner", "Talent Sherpa"])

    assert resolved == {"partner": "hiring_manager", "talent sherpa": "recruiter"}
    # only the uncached title went to the LLM
    assert "talent sherpa" in mock_llm.await_args.kwargs["user_prompt"]
    assert "partner" not in mock_llm.await_args.kwargs["user_prompt"]
    assert written.get(title_llm._cache_key("talent sherpa")) == "recruiter"


async def test_resolve_ambiguous_titles_fails_soft():
    with (
        patch.object(title_llm.search_cache_client, "get_json", new=AsyncMock(return_value=None)),
        patch.object(
            title_llm.llm_client,
            "generate_message",
            new=AsyncMock(side_effect=RuntimeError("provider down")),
        ),
    ):
        assert await title_llm.resolve_ambiguous_titles(["Mystery Title"]) == {}

    with (
        patch.object(title_llm.search_cache_client, "get_json", new=AsyncMock(return_value=None)),
        patch.object(
            title_llm.llm_client,
            "generate_message",
            new=AsyncMock(return_value={"draft": "not json at all"}),
        ),
    ):
        assert await title_llm.resolve_ambiguous_titles(["Mystery Title"]) == {}


# ---------------------------------------------------------------------------
# Startup-aware hiring-manager ranking
# ---------------------------------------------------------------------------

def test_startup_context_ranks_verified_founder_first():
    from app.services.people.ranking import _candidate_sort_key
    from app.utils.job_context import JobContext, extract_job_context

    founder = {
        "full_name": "Theo",
        "title": "Co-Founder & CTO",
        "profile_data": {"company_match_confidence": "verified"},
    }
    head_eng = {
        "full_name": "Imogen",
        "title": "Head of Engineering",
        "profile_data": {"company_match_confidence": "strong_signal"},
    }

    startup_ctx = JobContext(
        department="engineering", startup=True,
        manager_titles=["Head of Engineering", "Engineering Manager"],
    )
    bigco_ctx = JobContext(
        department="engineering", startup=False,
        manager_titles=["Head of Engineering", "Engineering Manager"],
    )

    startup_order = sorted(
        [head_eng, founder],
        key=lambda c: _candidate_sort_key(c, bucket="hiring_managers", context=startup_ctx),
    )
    assert startup_order[0]["full_name"] == "Theo"

    bigco_order = sorted(
        [head_eng, founder],
        key=lambda c: _candidate_sort_key(c, bucket="hiring_managers", context=bigco_ctx),
    )
    assert bigco_order[0]["full_name"] == "Imogen"

    # startup flag derives from the reserved job tags
    ctx = extract_job_context("Platform Engineer", "Build infra.", tags=["startup", "occupation:software_engineering"])
    assert ctx.startup is True
    ctx = extract_job_context("Platform Engineer", "Build infra.", tags=["occupation:software_engineering"])
    assert ctx.startup is False


def test_founder_exec_title_detector_word_boundaries():
    from app.services.people.titles import _is_founder_exec_title

    assert _is_founder_exec_title("Co-Founder & CTO") is True
    assert _is_founder_exec_title("Chief Technology Officer") is True
    assert _is_founder_exec_title("Founding Engineer") is True
    # "doctor" contains the letters c-t-o but must not match
    assert _is_founder_exec_title("Medical Doctor") is False
    assert _is_founder_exec_title("Director of Engineering") is False


# ---------------------------------------------------------------------------
# Occupation-aware job source routing (tech-source suppression for non-tech)
# ---------------------------------------------------------------------------

def test_suppress_tech_sources_helper():
    from app.services.job_service import _suppress_tech_sources

    # all industry-bound non-tech -> suppress
    assert _suppress_tech_sources(["healthcare"]) is True
    assert _suppress_tech_sources(["education_training", "healthcare"]) is True
    # any cross-industry / tech occupation present -> keep tech sources
    assert _suppress_tech_sources(["sales"]) is False
    assert _suppress_tech_sources(["software_engineering"]) is False
    assert _suppress_tech_sources(["healthcare", "sales"]) is False
    # empty -> keep (default behavior)
    assert _suppress_tech_sources([]) is False
    assert _suppress_tech_sources(None) is False


async def test_discover_routes_nontech_to_broad_aggregators():
    from app.services import job_service

    profile = MagicMock()
    profile.target_occupations = ["healthcare"]
    profile.target_roles = None
    profile.target_locations = []

    db = MagicMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = profile
    db.execute = AsyncMock(return_value=result)

    with (
        patch.object(job_service, "search_jobs", new=AsyncMock(return_value=[])) as mock_search,
        patch.object(job_service.newgrad_jobs_client, "search_newgrad_jobs", new=AsyncMock(return_value=[])) as mock_newgrad,
        patch.object(job_service, "_store_raw_jobs", new=AsyncMock(return_value=[])),
        patch.object(job_service, "_discover_ats_boards", new=AsyncMock(return_value=0)) as mock_ats,
    ):
        await job_service.discover_jobs(db, uuid.uuid4())

    # tech-only sources are gone; broad aggregators remain
    for call in mock_search.await_args_list:
        srcs = call.kwargs["sources"]
        assert "dice" not in srcs and "simplify" not in srcs and "jobicy" not in srcs
        assert "jsearch" in srcs and "adzuna" in srcs
    # newgrad + the 100 tech ATS boards are skipped entirely for healthcare
    mock_newgrad.assert_not_awaited()
    mock_ats.assert_not_awaited()
