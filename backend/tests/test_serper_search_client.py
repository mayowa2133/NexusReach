"""Unit tests for Serper search client."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.clients.serper_search_client import (
    search_exact_linkedin_profile,
    search_hiring_team,
    search_people,
    search_public_people,
)

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


class TestSearchPeople:
    async def test_returns_linkedin_results_with_serper_source(self):
        mock_resp = _mock_httpx_response(
            {
                "organic": [
                    {
                        "title": "Jane Doe - Software Engineer - Google | LinkedIn",
                        "link": "https://www.linkedin.com/in/janedoe",
                        "snippet": "Software Engineer at Google.",
                    }
                ]
            }
        )
        mock_client = _mock_client_with(mock_resp)

        with (
            patch("app.clients.serper_search_client.httpx.AsyncClient", return_value=mock_client),
            patch("app.clients.serper_search_client.settings") as s,
        ):
            s.serper_api_key = "serper-key"
            results = await search_people("Google", titles=["software engineer"])

        assert results[0]["source"] == "serper_search"
        payload = mock_client.post.call_args[1]["json"]
        headers = mock_client.post.call_args[1]["headers"]
        assert 'site:linkedin.com/in "Google"' in payload["q"]
        assert headers["X-API-KEY"] == "serper-key"

    async def test_search_exact_linkedin_profile_uses_name_and_company(self):
        mock_resp = _mock_httpx_response(
            {
                "organic": [
                    {
                        "title": "Lauren Tyson - Research Recruiter at Apple | LinkedIn",
                        "link": "https://www.linkedin.com/in/laurentyson",
                        "snippet": "Research Recruiter at Apple.",
                    }
                ]
            }
        )
        mock_client = _mock_client_with(mock_resp)

        with (
            patch("app.clients.serper_search_client.httpx.AsyncClient", return_value=mock_client),
            patch("app.clients.serper_search_client.settings") as s,
        ):
            s.serper_api_key = "serper-key"
            results = await search_exact_linkedin_profile("Lauren Tyson", "Apple")

        assert results[0]["source"] == "serper_search"
        assert mock_client.post.call_args[1]["json"]["q"] == 'site:linkedin.com/in "Lauren Tyson" "Apple"'

    async def test_search_exact_linkedin_profile_tries_title_hint_query(self):
        mock_resp = _mock_httpx_response(
            {
                "organic": [
                    {
                        "title": "Lauren Tyson - Research Recruiter at Apple | LinkedIn",
                        "link": "https://www.linkedin.com/in/laurentyson",
                        "snippet": "Research Recruiter at Apple.",
                    }
                ]
            }
        )
        mock_client = _mock_client_with(mock_resp)

        with (
            patch("app.clients.serper_search_client.httpx.AsyncClient", return_value=mock_client),
            patch("app.clients.serper_search_client.settings") as s,
        ):
            s.serper_api_key = "serper-key"
            await search_exact_linkedin_profile(
                "Lauren Tyson",
                "Apple",
                title_hints=["research recruiter"],
                team_keywords=["talent acquisition"],
                limit=3,
            )

        queries = [call.kwargs["json"]["q"] for call in mock_client.post.await_args_list]
        assert 'site:linkedin.com/in "Lauren Tyson" "Apple"' in queries[0]
        assert any('"research recruiter"' in query for query in queries)
        assert any('"talent acquisition"' in query for query in queries)

    async def test_search_exact_linkedin_profile_tries_name_variants(self):
        mock_resp = _mock_httpx_response({"organic": []})
        mock_client = _mock_client_with(mock_resp)

        with (
            patch("app.clients.serper_search_client.httpx.AsyncClient", return_value=mock_client),
            patch("app.clients.serper_search_client.settings") as s,
        ):
            s.serper_api_key = "serper-key"
            await search_exact_linkedin_profile(
                "Xu, Ting",
                "AppLovin",
                name_variants=["Ting Xu"],
                limit=3,
            )

        queries = [call.kwargs["json"]["q"] for call in mock_client.post.await_args_list]
        assert 'site:linkedin.com/in "Xu, Ting" "AppLovin"' in queries[0]
        assert any(query == 'site:linkedin.com/in "Ting Xu" "AppLovin"' for query in queries)


class TestPublicAndHiringTeam:
    async def test_search_public_people_returns_serper_public_web(self):
        mock_resp = _mock_httpx_response(
            {
                "organic": [
                    {
                        "title": "Andre Nguyen - Sr Technical Recruiter at Zip | The Org",
                        "link": "https://theorg.com/org/ziphq/org-chart/andre-nguyen",
                        "snippet": "Currently serving as a Sr Technical Recruiter at Zip.",
                    }
                ]
            }
        )
        mock_client = _mock_client_with(mock_resp)

        with (
            patch("app.clients.serper_search_client.httpx.AsyncClient", return_value=mock_client),
            patch("app.clients.serper_search_client.settings") as s,
        ):
            s.serper_api_key = "serper-key"
            results = await search_public_people("Zip", titles=["technical recruiter"], public_identity_terms=["ziphq"])

        assert results[0]["source"] == "serper_public_web"
        assert results[0]["profile_data"]["public_identity_slug"] == "ziphq"

    async def test_search_hiring_team_returns_serper_hiring_team(self):
        mock_resp = _mock_httpx_response(
            {
                "organic": [
                    {
                        "title": "Senior Engineer at Stripe",
                        "link": "https://linkedin.com/jobs/view/123",
                        "snippet": "Posted by Jane Smith for the payments team.",
                    }
                ]
            }
        )
        mock_client = _mock_client_with(mock_resp)

        with (
            patch("app.clients.serper_search_client.httpx.AsyncClient", return_value=mock_client),
            patch("app.clients.serper_search_client.settings") as s,
        ):
            s.serper_api_key = "serper-key"
            results = await search_hiring_team("Stripe", "Senior Engineer")

        assert results[0]["full_name"] == "Jane Smith"
        assert results[0]["source"] == "serper_hiring_team"
