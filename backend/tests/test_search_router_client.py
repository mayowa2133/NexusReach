"""Unit tests for provider routing and cache behavior."""

from unittest.mock import AsyncMock, patch

import pytest

from app.clients.search_router_client import (
    search_employment_sources,
    search_exact_linkedin_profile,
    search_hiring_team,
    search_people,
    search_recruiter_recovery_posts,
    search_recruiter_recovery_profiles,
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


async def test_search_hiring_team_records_provider_debug_trace():
    async def _mock_hiring_team(*args, **kwargs):
        kwargs["debug_trace"]["queries"] = ['site:linkedin.com/jobs "Intuit" "Software Developer 1 (Center of Money)" "Toronto"']
        return [
            {
                "full_name": "Hugo Godoy",
                "title": "Software Engineering Manager",
                "linkedin_url": "https://ca.linkedin.com/in/godoyhugopereira",
                "source": "searxng_hiring_team",
                "profile_data": {},
            }
        ]

    with (
        patch("app.clients.search_router_client.search_cache_client.get_json", new_callable=AsyncMock, return_value=None),
        patch("app.clients.search_router_client.search_cache_client.set_json", new_callable=AsyncMock),
        patch(
            "app.clients.search_router_client.searxng_search_client.search_hiring_team",
            new_callable=AsyncMock,
            side_effect=_mock_hiring_team,
        ) as mock_searxng,
        patch("app.clients.search_router_client.serper_search_client.search_hiring_team", new_callable=AsyncMock, return_value=[]),
        patch("app.clients.search_router_client.brave_search_client.search_hiring_team", new_callable=AsyncMock, return_value=[]),
        patch("app.clients.search_router_client.settings") as s,
    ):
        s.search_cache_ttl_seconds = 86400
        s.search_hiring_team_provider_order = "searxng,serper,brave"
        debug_traces: list[dict] = []
        results = await search_hiring_team(
            "Intuit",
            "Software Developer 1 (Center of Money)",
            team_keywords=["fullstack"],
            geo_terms=["Toronto", "Ontario", "Canada"],
            min_results=1,
            debug_traces=debug_traces,
        )

    assert len(results) == 1
    mock_searxng.assert_awaited_once()
    await_kwargs = mock_searxng.await_args.kwargs
    assert await_kwargs["geo_terms"] == ["Toronto", "Ontario", "Canada"]
    assert "debug_trace" in await_kwargs
    assert debug_traces[0]["provider"] == "searxng"
    assert debug_traces[0]["queries"]
    assert debug_traces[0]["sample_results"][0]["full_name"] == "Hugo Godoy"


async def test_search_people_interactive_profile_uses_tighter_provider_budget():
    with (
        patch("app.clients.search_router_client.search_cache_client.get_json", new_callable=AsyncMock, return_value=None),
        patch("app.clients.search_router_client.search_cache_client.set_json", new_callable=AsyncMock),
        patch(
            "app.clients.search_router_client.searxng_search_client.search_people",
            new_callable=AsyncMock,
            return_value=[],
        ) as mock_searxng,
        patch(
            "app.clients.search_router_client.brave_search_client.search_people",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch("app.clients.search_router_client.serper_search_client.search_people", new_callable=AsyncMock),
        patch("app.clients.search_router_client.google_search_client.search_people", new_callable=AsyncMock),
        patch("app.clients.search_router_client.settings") as s,
    ):
        s.search_cache_ttl_seconds = 86400
        s.search_linkedin_provider_order = "serper,searxng,google_cse,brave"
        debug_traces: list[dict] = []
        await search_people(
            "Intuit",
            titles=["Engineering Manager"],
            geo_terms=["Toronto", "Ontario"],
            min_results=3,
            debug_traces=debug_traces,
            search_profile="interactive",
        )

    mock_searxng.assert_awaited_once()


async def test_search_people_fast_interactive_profile_uses_single_provider_and_shorter_timeout():
    with (
        patch("app.clients.search_router_client.search_cache_client.get_json", new_callable=AsyncMock, return_value=None),
        patch("app.clients.search_router_client.search_cache_client.set_json", new_callable=AsyncMock),
        patch(
            "app.clients.search_router_client.searxng_search_client.search_people",
            new_callable=AsyncMock,
            return_value=[],
        ) as mock_searxng,
        patch(
            "app.clients.search_router_client.brave_search_client.search_people",
            new_callable=AsyncMock,
        ) as mock_brave,
        patch("app.clients.search_router_client.serper_search_client.search_people", new_callable=AsyncMock) as mock_serper,
        patch("app.clients.search_router_client.google_search_client.search_people", new_callable=AsyncMock) as mock_google,
        patch("app.clients.search_router_client.settings") as s,
    ):
        s.search_cache_ttl_seconds = 86400
        s.search_linkedin_provider_order = "serper,searxng,google_cse,brave"
        debug_traces: list[dict] = []
        await search_people(
            "Intuit",
            titles=["Engineering Manager"],
            geo_terms=["Toronto", "Ontario"],
            min_results=3,
            debug_traces=debug_traces,
            search_profile="interactive_fast",
        )

    mock_searxng.assert_awaited_once()
    mock_brave.assert_not_called()
    mock_serper.assert_not_called()
    mock_google.assert_not_called()
    assert debug_traces[0]["timeout_seconds"] == 2
    assert [trace["provider"] for trace in debug_traces] == ["searxng"]


async def test_search_exact_linkedin_profile_forwards_geo_terms():
    with (
        patch("app.clients.search_router_client.search_cache_client.get_json", new_callable=AsyncMock, return_value=None),
        patch("app.clients.search_router_client.search_cache_client.set_json", new_callable=AsyncMock),
        patch(
            "app.clients.search_router_client.searxng_search_client.search_exact_linkedin_profile",
            new_callable=AsyncMock,
            return_value=[],
        ) as mock_searxng,
        patch("app.clients.search_router_client.brave_search_client.search_exact_linkedin_profile", new_callable=AsyncMock, return_value=[]),
        patch("app.clients.search_router_client.serper_search_client.search_exact_linkedin_profile", new_callable=AsyncMock, return_value=[]),
        patch("app.clients.search_router_client.google_search_client.search_exact_linkedin_profile", new_callable=AsyncMock, return_value=[]),
        patch("app.clients.search_router_client.settings") as s,
    ):
        s.search_cache_ttl_seconds = 86400
        s.search_exact_linkedin_provider_order = "searxng,brave,serper,google_cse"
        await search_exact_linkedin_profile(
            "Reiss Simmons",
            "Intuit",
            title_hints=["Talent Acquisition Manager"],
            geo_terms=["Toronto", "Ontario", "Canada"],
            search_profile="interactive",
        )

    await_kwargs = mock_searxng.await_args.kwargs
    assert await_kwargs["geo_terms"] == ["Toronto", "Ontario", "Canada"]


async def test_search_recruiter_recovery_profiles_prefers_searxng_in_interactive_mode():
    with (
        patch("app.clients.search_router_client.search_cache_client.get_json", new_callable=AsyncMock, return_value=None),
        patch("app.clients.search_router_client.search_cache_client.set_json", new_callable=AsyncMock),
        patch(
            "app.clients.search_router_client.searxng_search_client.search_recruiter_recovery_profiles",
            new_callable=AsyncMock,
            return_value=[
                {
                    "full_name": "Reiss Simmons",
                    "title": "Talent Acquisition Leader",
                    "linkedin_url": "https://ca.linkedin.com/in/reisssimmons",
                    "source": "searxng_search",
                    "profile_data": {},
                }
            ],
        ) as mock_searxng,
        patch(
            "app.clients.search_router_client.brave_search_client.search_recruiter_recovery_profiles",
            new_callable=AsyncMock,
            return_value=[],
        ) as mock_brave,
        patch("app.clients.search_router_client.settings") as s,
    ):
        s.search_cache_ttl_seconds = 86400
        s.search_linkedin_provider_order = "searxng,brave"
        debug_traces: list[dict] = []
        results = await search_recruiter_recovery_profiles(
            "Intuit",
            team_keywords=["engineering hiring"],
            geo_terms=["Toronto", "Ontario", "Canada"],
            min_results=1,
            debug_traces=debug_traces,
            search_profile="interactive",
        )

    assert results[0]["profile_data"]["search_provider"] == "searxng"
    mock_searxng.assert_awaited_once()
    mock_brave.assert_not_called()
    assert debug_traces[0]["provider"] == "searxng"


async def test_search_recruiter_recovery_posts_records_provider_debug_trace():
    with (
        patch("app.clients.search_router_client.search_cache_client.get_json", new_callable=AsyncMock, return_value=None),
        patch("app.clients.search_router_client.search_cache_client.set_json", new_callable=AsyncMock),
        patch(
            "app.clients.search_router_client.searxng_search_client.search_recruiter_recovery_posts",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch(
            "app.clients.search_router_client.brave_search_client.search_recruiter_recovery_posts",
            new_callable=AsyncMock,
            return_value=[
                {
                    "full_name": "Reiss Simmons",
                    "title": "Talent Acquisition Leader",
                    "linkedin_url": "https://ca.linkedin.com/in/reisssimmons",
                    "source": "brave_public_web",
                    "profile_data": {},
                }
            ],
        ) as mock_brave,
        patch("app.clients.search_router_client.settings") as s,
    ):
        s.search_cache_ttl_seconds = 86400
        s.search_public_provider_order = "searxng,brave"
        debug_traces: list[dict] = []
        results = await search_recruiter_recovery_posts(
            "Intuit",
            geo_terms=["Toronto", "Ontario", "Canada"],
            min_results=1,
            debug_traces=debug_traces,
        )

    assert len(results) == 1
    mock_brave.assert_awaited_once()
    assert debug_traces[-1]["provider"] == "brave"
