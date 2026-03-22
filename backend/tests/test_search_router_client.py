"""Unit tests for provider routing and cache behavior."""

from unittest.mock import AsyncMock, patch

import pytest

from app.clients.search_router_client import (
    search_employment_sources,
    search_exact_linkedin_profile,
    search_people,
)

pytestmark = pytest.mark.asyncio


async def test_search_people_falls_through_to_brave_when_serper_is_empty():
    with (
        patch("app.clients.search_router_client.search_cache_client.get_json", new_callable=AsyncMock, return_value=None),
        patch("app.clients.search_router_client.search_cache_client.set_json", new_callable=AsyncMock),
        patch("app.clients.search_router_client.serper_search_client.search_people", new_callable=AsyncMock, return_value=[]),
        patch(
            "app.clients.search_router_client.brave_search_client.search_people",
            new_callable=AsyncMock,
            return_value=[
                {
                    "full_name": "Jane Doe",
                    "title": "Software Engineer",
                    "linkedin_url": "https://www.linkedin.com/in/janedoe",
                    "source": "brave_search",
                    "profile_data": {},
                }
            ],
        ) as mock_brave,
        patch("app.clients.search_router_client.google_search_client.search_people", new_callable=AsyncMock, return_value=[]),
        patch("app.clients.search_router_client.settings") as s,
    ):
        s.search_cache_ttl_seconds = 86400
        s.search_linkedin_provider_order = "serper,brave,google_cse"
        results = await search_people("Google", titles=["software engineer"], min_results=1)

    assert len(results) == 1
    assert results[0]["profile_data"]["search_provider"] == "brave"
    mock_brave.assert_awaited_once()


async def test_search_exact_linkedin_profile_uses_cached_provider_result():
    cached = [
        {
            "full_name": "Lauren Tyson",
            "title": "Research Recruiter",
            "linkedin_url": "https://www.linkedin.com/in/laurentyson",
            "source": "brave_search",
            "profile_data": {},
        }
    ]
    with (
        patch("app.clients.search_router_client.search_cache_client.get_json", new_callable=AsyncMock, return_value=cached),
        patch("app.clients.search_router_client.search_cache_client.set_json", new_callable=AsyncMock),
        patch("app.clients.search_router_client.brave_search_client.search_exact_linkedin_profile", new_callable=AsyncMock) as mock_brave,
        patch("app.clients.search_router_client.serper_search_client.search_exact_linkedin_profile", new_callable=AsyncMock),
        patch("app.clients.search_router_client.google_search_client.search_exact_linkedin_profile", new_callable=AsyncMock),
        patch("app.clients.search_router_client.settings") as s,
    ):
        s.search_exact_linkedin_provider_order = "brave,serper,google_cse"
        results = await search_exact_linkedin_profile("Lauren Tyson", "Apple")

    assert results[0]["profile_data"]["search_cache_hit"] is True
    assert results[0]["profile_data"]["search_provider"] == "brave"
    mock_brave.assert_not_called()


async def test_search_employment_sources_prefers_tavily_then_stops():
    with (
        patch("app.clients.search_router_client.search_cache_client.get_json", new_callable=AsyncMock, return_value=None),
        patch("app.clients.search_router_client.search_cache_client.set_json", new_callable=AsyncMock),
        patch(
            "app.clients.search_router_client.tavily_search_client.search_employment_sources",
            new_callable=AsyncMock,
            return_value=[
                {
                    "url": "https://theorg.com/org/ziphq/org-chart/andre-nguyen",
                    "title": "Andre Nguyen - The Org",
                    "description": "Andre Nguyen is a Sr Technical Recruiter at Zip.",
                    "source": "tavily_public_web",
                }
            ],
        ) as mock_tavily,
        patch("app.clients.search_router_client.serper_search_client.search_employment_sources", new_callable=AsyncMock) as mock_serper,
        patch("app.clients.search_router_client.brave_search_client.search_employment_sources", new_callable=AsyncMock) as mock_brave,
        patch("app.clients.search_router_client.settings") as s,
    ):
        s.search_cache_ttl_seconds = 86400
        s.search_employment_provider_order = "tavily,serper,brave"
        results = await search_employment_sources("Andre Nguyen", "Zip", min_results=1)

    assert results[0]["search_provider"] == "tavily"
    mock_tavily.assert_awaited_once()
    mock_serper.assert_not_called()
    mock_brave.assert_not_called()
