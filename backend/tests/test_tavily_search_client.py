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
