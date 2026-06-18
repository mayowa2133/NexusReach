"""Unit tests for the free public-web profile enricher (Proxycurl replacement)."""

from unittest.mock import AsyncMock, patch

from app.clients import public_profile_client
from app.clients.public_profile_client import (
    _name_from_slug,
    _parse_profile_title,
    enrich_profile,
)

# asyncio_mode = auto (pytest.ini) runs async tests without a marker, so this
# module mixes sync parser tests and async enrich tests without a module mark.


def test_name_from_slug_drops_trailing_id_tokens():
    assert _name_from_slug("jane-doe-1a2b3c4d") == "Jane Doe"
    assert _name_from_slug("john-smith-12345") == "John Smith"
    assert _name_from_slug("maria-de-la-cruz") == "Maria De La Cruz"
    assert _name_from_slug("") == ""


def test_parse_profile_title_name_title_company():
    name, title, company = _parse_profile_title("Jane Doe - Staff Engineer - Stripe | LinkedIn")
    assert (name, title, company) == ("Jane Doe", "Staff Engineer", "Stripe")


def test_parse_profile_title_title_at_company():
    name, title, company = _parse_profile_title("John Smith - Senior Recruiter at Figma | LinkedIn")
    assert name == "John Smith"
    assert title == "Senior Recruiter"
    assert company == "Figma"


def test_parse_profile_title_handles_en_dash_separator():
    name, title, company = _parse_profile_title("Ana Reyes – Product Manager – Notion | LinkedIn")
    assert (name, title, company) == ("Ana Reyes", "Product Manager", "Notion")


def test_parse_profile_title_name_only():
    name, title, company = _parse_profile_title("Sam Lee | LinkedIn")
    assert name == "Sam Lee"
    assert title == ""
    assert company == ""


async def test_enrich_profile_returns_parsed_snippet_for_matching_url():
    items = [
        {
            "title": "Jane Doe - Staff Engineer - Stripe | LinkedIn",
            "url": "https://www.linkedin.com/in/jane-doe-1a2b3c4d/",
            "content": "San Francisco · Staff Engineer at Stripe",
        }
    ]
    with patch.object(
        public_profile_client.searxng_search_client,
        "_run_searxng_query",
        new=AsyncMock(return_value=items),
    ):
        result = await enrich_profile("https://www.linkedin.com/in/jane-doe-1a2b3c4d")

    assert result is not None
    assert result["full_name"] == "Jane Doe"
    assert result["title"] == "Staff Engineer"
    assert result["company"] == "Stripe"
    assert result["linkedin_url"] == "https://www.linkedin.com/in/jane-doe-1a2b3c4d"
    assert result["source"] == "public_web"
    assert result["profile_data"]["enrichment_source"] == "searxng_serp_snippet"


async def test_enrich_profile_ignores_results_for_a_different_profile():
    """A SERP hit pointing at someone else's profile must not be returned."""
    items = [
        {
            "title": "Someone Else - VP Sales - Acme | LinkedIn",
            "url": "https://www.linkedin.com/in/someone-else/",
            "content": "",
        }
    ]
    with patch.object(
        public_profile_client.searxng_search_client,
        "_run_searxng_query",
        new=AsyncMock(return_value=items),
    ):
        result = await enrich_profile("https://www.linkedin.com/in/jane-doe-1a2b3c4d")

    assert result is None


async def test_enrich_profile_returns_none_when_searxng_empty():
    with patch.object(
        public_profile_client.searxng_search_client,
        "_run_searxng_query",
        new=AsyncMock(return_value=[]),
    ):
        result = await enrich_profile("https://www.linkedin.com/in/jane-doe-1a2b3c4d")

    assert result is None


async def test_enrich_profile_returns_none_for_non_linkedin_url():
    # Should short-circuit before any search call.
    mock_query = AsyncMock(return_value=[])
    with patch.object(public_profile_client.searxng_search_client, "_run_searxng_query", new=mock_query):
        result = await enrich_profile("https://example.com/team/jane")

    assert result is None
    mock_query.assert_not_called()
