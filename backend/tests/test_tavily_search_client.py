"""Unit tests for Tavily search client."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.clients.tavily_search_client import search_employment_sources, search_public_people

pytestmark = pytest.mark.asyncio


def _mock_httpx_response(json_data, status_code=200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.raise_for_status = MagicMock()
    return resp


def _mock_client_with(response):
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=response)
    return mock_client


async def test_search_employment_sources_returns_normalized_results():
    mock_resp = _mock_httpx_response(
        {
            "results": [
                {
                    "title": "Andre Nguyen - The Org",
                    "url": "https://theorg.com/org/ziphq/org-chart/andre-nguyen?ref=search",
                    "content": "Andre Nguyen is a Sr Technical Recruiter at Zip.",
                }
            ]
        }
    )
    mock_client = _mock_client_with(mock_resp)

    with (
        patch("app.clients.tavily_search_client.httpx.AsyncClient", return_value=mock_client),
        patch("app.clients.tavily_search_client.settings") as s,
    ):
        s.tavily_api_key = "tavily-key"
        results = await search_employment_sources(
            "Andre Nguyen",
            "Zip",
            company_domain="ziphq.com",
            public_identity_terms=["ziphq"],
        )

    assert results == [
        {
            "url": "https://theorg.com/org/ziphq/org-chart/andre-nguyen",
            "title": "Andre Nguyen - The Org",
            "description": "Andre Nguyen is a Sr Technical Recruiter at Zip.",
            "source": "tavily_public_web",
        }
    ]
    include_domains = mock_client.post.call_args[1]["json"]["include_domains"]
    assert "ziphq.com" in include_domains


async def test_search_public_people_returns_tavily_public_web():
    mock_resp = _mock_httpx_response(
        {
            "results": [
                {
                    "title": "Lauren Tyson - Research Recruiter at Apple | The Org",
                    "url": "https://theorg.com/org/apple/org-chart/lauren-tyson",
                    "content": "Lauren Tyson is a Research Recruiter at Apple.",
                }
            ]
        }
    )
    mock_client = _mock_client_with(mock_resp)

    with (
        patch("app.clients.tavily_search_client.httpx.AsyncClient", return_value=mock_client),
        patch("app.clients.tavily_search_client.settings") as s,
    ):
        s.tavily_api_key = "tavily-key"
        results = await search_public_people("Apple", titles=["research recruiter"])

    assert results[0]["source"] == "tavily_public_web"
    assert results[0]["profile_data"]["public_identity_slug"] == "apple"


async def test_search_public_people_uses_manager_geo_queries_for_engineering_leaders():
    mock_resp = _mock_httpx_response(
        {
            "results": [
                {
                    "title": "Hugo Godoy - Software Engineering Manager at Intuit | LinkedIn",
                    "url": "https://ca.linkedin.com/in/godoyhugopereira",
                    "content": "Hugo Godoy Intuit Toronto, Ontario, Canada About Software Engineering Manager.",
                }
            ]
        }
    )
    mock_client = _mock_client_with(mock_resp)

    with (
        patch("app.clients.tavily_search_client.httpx.AsyncClient", return_value=mock_client),
        patch("app.clients.tavily_search_client.settings") as s,
    ):
        s.tavily_api_key = "tavily-key"
        results = await search_public_people(
            "Intuit",
            titles=["Engineering Manager", "Director of Engineering"],
            team_keywords=["engineering leader"],
            public_identity_terms=["intuit"],
            geo_terms=["Toronto", "Greater Toronto Area", "Ontario", "Canada"],
        )

    assert results
    queries = [call.kwargs["json"]["query"] for call in mock_client.post.call_args_list]
    assert any("Software Engineering Manager" in query for query in queries)
    assert any("Intuit Canada" in query for query in queries)
    assert any("Toronto" in query for query in queries)


async def test_search_public_people_uses_recruiter_targeted_queries():
    mock_resp = _mock_httpx_response(
        {
            "results": [
                {
                    "title": "Reiss Simmons - Intuit | LinkedIn",
                    "url": "https://ca.linkedin.com/in/reisssimmons",
                    "content": "Reiss Simmons Intuit Canada About I lead the Talent Acquisition team at Intuit responsible for hiring in Canada.",
                }
            ]
        }
    )
    mock_client = _mock_client_with(mock_resp)

    with (
        patch("app.clients.tavily_search_client.httpx.AsyncClient", return_value=mock_client),
        patch("app.clients.tavily_search_client.settings") as s,
    ):
        s.tavily_api_key = "tavily-key"
        results = await search_public_people(
            "Intuit",
            titles=["Technical Recruiter", "Recruiter"],
            team_keywords=["engineering hiring"],
            public_identity_terms=["intuit"],
            geo_terms=["Toronto", "Ontario", "Canada"],
        )

    assert results
    queries = [call.kwargs["json"]["query"] for call in mock_client.post.call_args_list]
    assert any("recruiter" in query.lower() for query in queries)
    assert any("talent acquisition" in query.lower() for query in queries)
    assert any("lead talent acquisition" in query.lower() or "hiring in canada" in query.lower() for query in queries)


async def test_search_public_people_prefers_recruiter_queries_when_titles_include_manager_words():
    mock_resp = _mock_httpx_response(
        {
            "results": [
                {
                    "title": "Reiss Simmons - Intuit | LinkedIn",
                    "url": "https://ca.linkedin.com/in/reisssimmons",
                    "content": "Reiss Simmons Intuit Toronto, Ontario, Canada About I lead Talent Acquisition for Canada.",
                }
            ]
        }
    )
    mock_client = _mock_client_with(mock_resp)

    with (
        patch("app.clients.tavily_search_client.httpx.AsyncClient", return_value=mock_client),
        patch("app.clients.tavily_search_client.settings") as s,
    ):
        s.tavily_api_key = "tavily-key"
        results = await search_public_people(
            "Intuit",
            titles=["Talent Acquisition Manager", "Head of Talent Acquisition"],
            team_keywords=["engineering hiring"],
            public_identity_terms=["intuit"],
            geo_terms=["Toronto", "Ontario", "Canada"],
        )

    assert results
    queries = [call.kwargs["json"]["query"] for call in mock_client.post.call_args_list]
    assert any("talent acquisition" in query.lower() for query in queries)
    assert not any("engineering manager" in query.lower() for query in queries)


async def test_search_public_people_uses_peer_targeted_queries():
    mock_resp = _mock_httpx_response(
        {
            "results": [
                {
                    "title": "James Bonvivere - Software Engineer at Intuit | LinkedIn",
                    "url": "https://ca.linkedin.com/in/james-bonvivere",
                    "content": "Software Engineer at Intuit in Toronto, Ontario, Canada.",
                }
            ]
        }
    )
    mock_client = _mock_client_with(mock_resp)

    with (
        patch("app.clients.tavily_search_client.httpx.AsyncClient", return_value=mock_client),
        patch("app.clients.tavily_search_client.settings") as s,
    ):
        s.tavily_api_key = "tavily-key"
        results = await search_public_people(
            "Intuit",
            titles=["Software Developer 1 (Center of Money)", "Software Engineer"],
            team_keywords=["fullstack"],
            public_identity_terms=["intuit"],
            geo_terms=["Toronto", "Ontario", "Canada"],
        )

    assert results
    queries = [call.kwargs["json"]["query"] for call in mock_client.post.call_args_list]
    assert any("Software Developer 1" in query or "Software Engineer" in query for query in queries)
    assert any("fullstack" in query.lower() or "software engineer" in query.lower() for query in queries)
