"""Tests for non-technical people sources: company-site leaders + news quotes."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.clients import tavily_search_client
from app.services.people import company_site

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Company-site leadership parser
# ---------------------------------------------------------------------------

def test_looks_like_team_page():
    good = {"text": ("Our leadership team drives Acme forward. " * 6) +
                    "Jane Doe, Chief Revenue Officer. Sam Lee, VP of Marketing. "
                    "Pat Fox, Head of Sales. Founder and CEO Max Stone leads the executive team."}
    bad = {"text": "Buy our product today. Pricing and features."}
    assert company_site._looks_like_team_page(good) is True
    assert company_site._looks_like_team_page(bad) is False
    assert company_site._looks_like_team_page(None) is False


async def test_discover_company_site_leaders_extracts_and_shapes():
    page_text = (
        "Leadership team. Rhea Vega is our Chief Revenue Officer. "
        "Tom Webb, VP of Marketing. Dana Fox leads as Director of Sales."
    )
    llm_json = '[{"name":"Rhea Vega","title":"Chief Revenue Officer"},' \
               '{"name":"Tom Webb","title":"VP of Marketing"},' \
               '{"name":"Dana Fox","title":"Director of Sales"}]'
    with (
        patch.object(company_site.search_cache_client, "get_json", new=AsyncMock(return_value=None)),
        patch.object(company_site.search_cache_client, "set_json", new=AsyncMock()),
        patch.object(company_site, "_fetch_team_page",
                     new=AsyncMock(return_value=("https://acme.com/leadership", page_text))),
        patch.object(company_site.llm_client, "generate_message",
                     new=AsyncMock(return_value={"draft": llm_json})),
    ):
        leaders = await company_site.discover_company_site_leaders("Acme", "acme.com")

    by_name = {c["full_name"]: c for c in leaders}
    assert "Rhea Vega" in by_name
    assert by_name["Rhea Vega"]["source"] == "company_site"
    assert by_name["Rhea Vega"]["_company_site_leader"] is True
    assert by_name["Rhea Vega"]["profile_data"]["company_match_confidence"] == "strong_signal"
    assert len(leaders) == 3


async def test_company_site_uses_cache_when_present():
    cached = [{"name": "Cached Exec", "title": "CFO", "url": "https://acme.com/about"}]
    with (
        patch.object(company_site.search_cache_client, "get_json", new=AsyncMock(return_value=cached)),
        patch.object(company_site, "_fetch_team_page", new=AsyncMock()) as mock_fetch,
    ):
        leaders = await company_site.discover_company_site_leaders("Acme", "acme.com")
    mock_fetch.assert_not_awaited()  # cache short-circuits fetch
    assert leaders[0]["full_name"] == "Cached Exec"


async def test_company_site_fails_soft():
    # no domain -> empty, no calls
    assert await company_site.discover_company_site_leaders("Acme", None) == []
    # page not found -> empty (and caches the negative)
    with (
        patch.object(company_site.search_cache_client, "get_json", new=AsyncMock(return_value=None)),
        patch.object(company_site.search_cache_client, "set_json", new=AsyncMock()),
        patch.object(company_site, "_fetch_team_page", new=AsyncMock(return_value=None)),
    ):
        assert await company_site.discover_company_site_leaders("Acme", "acme.com") == []


# ---------------------------------------------------------------------------
# News / PR executive-quote mining
# ---------------------------------------------------------------------------

async def test_search_executive_quotes_extracts_named_execs():
    results = [
        {"title": "Acme appoints new revenue chief",
         "content": 'Acme today announced that Jane Carter, Chief Revenue Officer, will lead '
                    'global sales. "We are thrilled," said Carter.',
         "url": "https://news.example.com/acme"},
        {"title": "Unrelated company news",
         "content": "Globex hires Bob Smith, VP of Marketing.",
         "url": "https://news.example.com/globex"},
    ]
    with patch.object(tavily_search_client, "_run_tavily_query", new=AsyncMock(return_value=results)):
        cands = await tavily_search_client.search_executive_quotes("Acme", ["Chief Revenue Officer"])

    names = [c["full_name"] for c in cands]
    assert "Jane Carter" in names
    # the Globex result is dropped (company token "acme" absent)
    assert "Bob Smith" not in names
    jane = next(c for c in cands if c["full_name"] == "Jane Carter")
    assert jane["source"] == "news_quote"
    assert "Chief Revenue Officer" in jane["title"]


async def test_search_executive_quotes_fails_soft():
    with patch.object(tavily_search_client, "_run_tavily_query", new=AsyncMock(return_value=[])):
        assert await tavily_search_client.search_executive_quotes("Acme", []) == []
    assert await tavily_search_client.search_executive_quotes("", []) == []


# ---------------------------------------------------------------------------
# Ranking: published leaders beat generic x-ray, below team-confirmed
# ---------------------------------------------------------------------------

def test_published_leader_ranks_above_generic_xray():
    from app.services.people.candidates import _prepare_candidates
    from app.utils.job_context import JobContext

    ctx = JobContext(department="sales", occupation_keys=["sales"],
                     team_keywords=["strategic accounts"], manager_titles=["Sales Manager"], seniority="mid")
    site_leader = {
        "full_name": "Site Leader", "title": "Director of Sales", "source": "company_site",
        "snippet": "Listed on Acme's leadership page as Director of Sales",
        "_company_site_leader": True, "_employment_status": "current",
        "profile_data": {"company_match_confidence": "strong_signal"},
    }
    generic = {
        "full_name": "Generic Hit", "title": "Sales Manager", "source": "brave_search",
        "snippet": "Sales Manager at Acme", "_employment_status": "current",
        "profile_data": {"company_match_confidence": "strong_signal"},
    }
    ranked = _prepare_candidates(
        [generic, site_leader], company_name="Acme", public_identity_slugs=["acme"],
        bucket="hiring_managers", context=ctx, limit=5,
    )
    assert ranked[0]["full_name"] == "Site Leader"
