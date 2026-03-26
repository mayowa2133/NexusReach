"""Unit tests for Google Custom Search API client — LinkedIn X-ray people discovery."""

import pytest
from unittest.mock import patch, AsyncMock, MagicMock

from app.clients.google_search_client import search_people, _parse_linkedin_result

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
    mock_client.get = AsyncMock(return_value=response)
    return mock_client


class TestParseLinkedInResult:
    """Tests for _parse_linkedin_result() — parsing Google CSE results."""

    def test_standard_format(self):
        item = {
            "title": "Jane Doe - Software Engineer - Google | LinkedIn",
            "link": "https://www.linkedin.com/in/janedoe",
        }
        result = _parse_linkedin_result(item, "Google")
        assert result is not None
        assert result["full_name"] == "Jane Doe"
        assert result["title"] == "Software Engineer"
        assert result["linkedin_url"] == "https://www.linkedin.com/in/janedoe"
        assert result["source"] == "google_cse"

    def test_at_format(self):
        item = {
            "title": "John Smith - Senior Recruiter at Stripe | LinkedIn",
            "link": "https://www.linkedin.com/in/johnsmith",
        }
        result = _parse_linkedin_result(item, "Stripe")
        assert result is not None
        assert result["full_name"] == "John Smith"
        assert result["title"] == "Senior Recruiter"

    def test_name_only(self):
        item = {
            "title": "Alice Johnson | LinkedIn",
            "link": "https://www.linkedin.com/in/alicejohnson",
        }
        result = _parse_linkedin_result(item, "Google")
        assert result is not None
        assert result["full_name"] == "Alice Johnson"
        assert result["title"] == ""

    def test_strips_query_params_from_url(self):
        item = {
            "title": "Bob Lee - Engineer | LinkedIn",
            "link": "https://www.linkedin.com/in/boblee?trk=public_profile",
        }
        result = _parse_linkedin_result(item, "Google")
        assert result["linkedin_url"] == "https://www.linkedin.com/in/boblee"

    def test_rejects_non_profile_urls(self):
        item = {
            "title": "Google | LinkedIn",
            "link": "https://www.linkedin.com/company/google",
        }
        result = _parse_linkedin_result(item, "Google")
        assert result is None

    def test_rejects_empty_link(self):
        item = {"title": "Test | LinkedIn", "link": ""}
        result = _parse_linkedin_result(item, "Google")
        assert result is None


class TestSearchPeople:
    """Tests for search_people() — Google CSE LinkedIn X-ray search."""

    async def test_returns_parsed_results(self):
        mock_resp = _mock_httpx_response({
            "items": [
                {
                    "title": "Jane Doe - Software Engineer - Google | LinkedIn",
                    "link": "https://www.linkedin.com/in/janedoe",
                },
                {
                    "title": "Bob Smith - Senior Developer - Google | LinkedIn",
                    "link": "https://www.linkedin.com/in/bobsmith",
                },
            ]
        })
        mock_client = _mock_client_with(mock_resp)

        with (
            patch("app.clients.google_search_client.httpx.AsyncClient", return_value=mock_client),
            patch("app.clients.google_search_client.settings") as s,
        ):
            s.google_api_key = "goog-key"
            s.google_cse_id = "cse-id"
            results = await search_people("Google", titles=["software engineer"])

        assert len(results) == 2
        assert results[0]["full_name"] == "Jane Doe"
        assert results[1]["full_name"] == "Bob Smith"

        # Verify query construction
        params = mock_client.get.call_args[1]["params"]
        assert "site:linkedin.com/in" in params["q"]
        assert '"Google"' in params["q"]
        assert params["key"] == "goog-key"
        assert params["cx"] == "cse-id"

    async def test_returns_empty_when_no_api_key(self):
        with patch("app.clients.google_search_client.settings") as s:
            s.google_api_key = ""
            s.google_cse_id = "cse-id"
            results = await search_people("Google")
        assert results == []

    async def test_returns_empty_when_no_cse_id(self):
        with patch("app.clients.google_search_client.settings") as s:
            s.google_api_key = "key"
            s.google_cse_id = ""
            results = await search_people("Google")
        assert results == []

    async def test_returns_empty_on_403(self):
        mock_client = _mock_client_with(_mock_httpx_response({}, status_code=403))

        with (
            patch("app.clients.google_search_client.httpx.AsyncClient", return_value=mock_client),
            patch("app.clients.google_search_client.settings") as s,
        ):
            s.google_api_key = "key"
            s.google_cse_id = "cse-id"
            results = await search_people("Google")

        assert results == []

    async def test_returns_empty_on_no_items(self):
        mock_client = _mock_client_with(_mock_httpx_response({}))

        with (
            patch("app.clients.google_search_client.httpx.AsyncClient", return_value=mock_client),
            patch("app.clients.google_search_client.settings") as s,
        ):
            s.google_api_key = "key"
            s.google_cse_id = "cse-id"
            results = await search_people("Google")

        assert results == []

    async def test_filters_non_profile_results(self):
        mock_resp = _mock_httpx_response({
            "items": [
                {
                    "title": "Jane Doe - Engineer | LinkedIn",
                    "link": "https://www.linkedin.com/in/janedoe",
                },
                {
                    "title": "Google | LinkedIn",
                    "link": "https://www.linkedin.com/company/google",
                },
            ]
        })
        mock_client = _mock_client_with(mock_resp)

        with (
            patch("app.clients.google_search_client.httpx.AsyncClient", return_value=mock_client),
            patch("app.clients.google_search_client.settings") as s,
        ):
            s.google_api_key = "key"
            s.google_cse_id = "cse-id"
            results = await search_people("Google")

        assert len(results) == 1
        assert results[0]["full_name"] == "Jane Doe"

    async def test_limits_title_keywords(self):
        """Each query batch uses at most 2 titles."""
        mock_client = _mock_client_with(_mock_httpx_response({"items": []}))

        with (
            patch("app.clients.google_search_client.httpx.AsyncClient", return_value=mock_client),
            patch("app.clients.google_search_client.settings") as s,
        ):
            s.google_api_key = "key"
            s.google_cse_id = "cse-id"
            await search_people("Google", titles=["a", "b", "c", "d"])

        queries = [call[1]["params"]["q"] for call in mock_client.get.call_args_list]
        # Both batches should appear across queries
        assert any('"a"' in q and '"b"' in q for q in queries)
        assert any('"c"' in q and '"d"' in q for q in queries)
        # No single query should contain more than 2 title terms
        for q in queries:
            title_count = sum(1 for t in ["a", "b", "c", "d"] if f'"{t}"' in q)
            assert title_count <= 2, f"Query has {title_count} titles: {q}"
