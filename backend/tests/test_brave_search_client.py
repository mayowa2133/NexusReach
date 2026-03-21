"""Unit tests for Brave Search API client — LinkedIn X-ray people discovery."""

import pytest
from unittest.mock import patch, AsyncMock, MagicMock

from app.clients.brave_search_client import (
    search_people, _parse_linkedin_result,
    search_hiring_team, _parse_hiring_team_result,
    _parse_public_people_result, search_public_people,
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
    mock_client.get = AsyncMock(return_value=response)
    return mock_client


class TestParseLinkedInResult:
    """Tests for _parse_linkedin_result() — parsing Brave search results."""

    def test_standard_format(self):
        item = {
            "title": "Jane Doe - Software Engineer - Google | LinkedIn",
            "url": "https://www.linkedin.com/in/janedoe",
        }
        result = _parse_linkedin_result(item, "Google")
        assert result is not None
        assert result["full_name"] == "Jane Doe"
        assert result["title"] == "Software Engineer"
        assert result["linkedin_url"] == "https://www.linkedin.com/in/janedoe"
        assert result["source"] == "brave_search"

    def test_at_format(self):
        item = {
            "title": "John Smith - Senior Recruiter at Stripe | LinkedIn",
            "url": "https://www.linkedin.com/in/johnsmith",
        }
        result = _parse_linkedin_result(item, "Stripe")
        assert result is not None
        assert result["full_name"] == "John Smith"
        assert result["title"] == "Senior Recruiter"

    def test_name_only(self):
        item = {
            "title": "Alice Johnson | LinkedIn",
            "url": "https://www.linkedin.com/in/alicejohnson",
        }
        result = _parse_linkedin_result(item, "Google")
        assert result is not None
        assert result["full_name"] == "Alice Johnson"
        assert result["title"] == ""

    def test_strips_query_params_from_url(self):
        item = {
            "title": "Bob Lee - Engineer | LinkedIn",
            "url": "https://www.linkedin.com/in/boblee?trk=public_profile",
        }
        result = _parse_linkedin_result(item, "Google")
        assert result["linkedin_url"] == "https://www.linkedin.com/in/boblee"

    def test_rejects_non_profile_urls(self):
        item = {
            "title": "Google | LinkedIn",
            "url": "https://www.linkedin.com/company/google",
        }
        result = _parse_linkedin_result(item, "Google")
        assert result is None

    def test_rejects_empty_url(self):
        item = {"title": "Test | LinkedIn", "url": ""}
        result = _parse_linkedin_result(item, "Google")
        assert result is None

    def test_captures_snippet(self):
        item = {
            "title": "Jane Doe - Engineer | LinkedIn",
            "url": "https://www.linkedin.com/in/janedoe",
            "description": "Jane works on the payments team at Stripe.",
        }
        result = _parse_linkedin_result(item, "Stripe")
        assert result is not None
        assert result["snippet"] == "Jane works on the payments team at Stripe."

    def test_snippet_defaults_to_empty(self):
        item = {
            "title": "Jane Doe - Engineer | LinkedIn",
            "url": "https://www.linkedin.com/in/janedoe",
        }
        result = _parse_linkedin_result(item, "Stripe")
        assert result["snippet"] == ""


class TestSearchPeople:
    """Tests for search_people() — Brave Search LinkedIn X-ray search."""

    async def test_returns_parsed_results(self):
        mock_resp = _mock_httpx_response({
            "web": {
                "results": [
                    {
                        "title": "Jane Doe - Software Engineer - Google | LinkedIn",
                        "url": "https://www.linkedin.com/in/janedoe",
                    },
                    {
                        "title": "Bob Smith - Senior Developer - Google | LinkedIn",
                        "url": "https://www.linkedin.com/in/bobsmith",
                    },
                ]
            }
        })
        mock_client = _mock_client_with(mock_resp)

        with (
            patch("app.clients.brave_search_client.httpx.AsyncClient", return_value=mock_client),
            patch("app.clients.brave_search_client.settings") as s,
        ):
            s.brave_api_key = "brave-key"
            results = await search_people("Google", titles=["software engineer"])

        assert len(results) == 2
        assert results[0]["full_name"] == "Jane Doe"
        assert results[1]["full_name"] == "Bob Smith"

        # Verify query construction
        params = mock_client.get.call_args[1]["params"]
        assert "site:linkedin.com/in" in params["q"]
        assert '"Google"' in params["q"]

        # Verify auth header
        headers = mock_client.get.call_args[1]["headers"]
        assert headers["X-Subscription-Token"] == "brave-key"

    async def test_returns_empty_when_no_api_key(self):
        with patch("app.clients.brave_search_client.settings") as s:
            s.brave_api_key = ""
            results = await search_people("Google")
        assert results == []

    async def test_returns_empty_on_401(self):
        mock_client = _mock_client_with(_mock_httpx_response({}, status_code=401))

        with (
            patch("app.clients.brave_search_client.httpx.AsyncClient", return_value=mock_client),
            patch("app.clients.brave_search_client.settings") as s,
        ):
            s.brave_api_key = "key"
            results = await search_people("Google")

        assert results == []

    async def test_returns_empty_on_403(self):
        mock_client = _mock_client_with(_mock_httpx_response({}, status_code=403))

        with (
            patch("app.clients.brave_search_client.httpx.AsyncClient", return_value=mock_client),
            patch("app.clients.brave_search_client.settings") as s,
        ):
            s.brave_api_key = "key"
            results = await search_people("Google")

        assert results == []

    async def test_returns_empty_on_429(self):
        mock_client = _mock_client_with(_mock_httpx_response({}, status_code=429))

        with (
            patch("app.clients.brave_search_client.httpx.AsyncClient", return_value=mock_client),
            patch("app.clients.brave_search_client.settings") as s,
        ):
            s.brave_api_key = "key"
            results = await search_people("Google")

        assert results == []

    async def test_returns_empty_on_no_results(self):
        mock_client = _mock_client_with(_mock_httpx_response({"web": {"results": []}}))

        with (
            patch("app.clients.brave_search_client.httpx.AsyncClient", return_value=mock_client),
            patch("app.clients.brave_search_client.settings") as s,
        ):
            s.brave_api_key = "key"
            results = await search_people("Google")

        assert results == []

    async def test_filters_non_profile_results(self):
        mock_resp = _mock_httpx_response({
            "web": {
                "results": [
                    {
                        "title": "Jane Doe - Engineer | LinkedIn",
                        "url": "https://www.linkedin.com/in/janedoe",
                    },
                    {
                        "title": "Google | LinkedIn",
                        "url": "https://www.linkedin.com/company/google",
                    },
                ]
            }
        })
        mock_client = _mock_client_with(mock_resp)

        with (
            patch("app.clients.brave_search_client.httpx.AsyncClient", return_value=mock_client),
            patch("app.clients.brave_search_client.settings") as s,
        ):
            s.brave_api_key = "key"
            results = await search_people("Google")

        assert len(results) == 1
        assert results[0]["full_name"] == "Jane Doe"

    async def test_limits_title_keywords(self):
        """Only first 2 titles are used to keep query focused."""
        mock_client = _mock_client_with(_mock_httpx_response({"web": {"results": []}}))

        with (
            patch("app.clients.brave_search_client.httpx.AsyncClient", return_value=mock_client),
            patch("app.clients.brave_search_client.settings") as s,
        ):
            s.brave_api_key = "key"
            await search_people("Google", titles=["a", "b", "c", "d"])

        query = mock_client.get.call_args[1]["params"]["q"]
        assert '"a"' in query
        assert '"b"' in query
        assert '"c"' not in query

    async def test_team_keywords_appended_to_query(self):
        """Team keywords are added to the search query."""
        mock_client = _mock_client_with(_mock_httpx_response({"web": {"results": []}}))

        with (
            patch("app.clients.brave_search_client.httpx.AsyncClient", return_value=mock_client),
            patch("app.clients.brave_search_client.settings") as s,
        ):
            s.brave_api_key = "key"
            await search_people("Stripe", titles=["engineer"], team_keywords=["payments"])

        query = mock_client.get.call_args[1]["params"]["q"]
        assert '"payments"' in query
        assert "site:linkedin.com/in" in query
        assert '"Stripe"' in query

    async def test_team_keywords_uses_only_first(self):
        """Only the first team keyword is used to avoid over-constraining."""
        mock_client = _mock_client_with(_mock_httpx_response({"web": {"results": []}}))

        with (
            patch("app.clients.brave_search_client.httpx.AsyncClient", return_value=mock_client),
            patch("app.clients.brave_search_client.settings") as s,
        ):
            s.brave_api_key = "key"
            await search_people("Google", team_keywords=["backend", "api", "platform"])

        query = mock_client.get.call_args[1]["params"]["q"]
        assert '"backend"' in query
        assert '"api"' not in query
        assert '"platform"' not in query

    async def test_empty_team_keywords_ignored(self):
        """Empty team_keywords list doesn't affect the query."""
        mock_client = _mock_client_with(_mock_httpx_response({"web": {"results": []}}))

        with (
            patch("app.clients.brave_search_client.httpx.AsyncClient", return_value=mock_client),
            patch("app.clients.brave_search_client.settings") as s,
        ):
            s.brave_api_key = "key"
            await search_people("Google", titles=["engineer"], team_keywords=[])

        query = mock_client.get.call_args[1]["params"]["q"]
        assert query == 'site:linkedin.com/in "Google" "engineer"'


class TestPublicPeople:
    def test_parse_public_people_result_extracts_theorg_identity_hints(self):
        item = {
            "title": "Andre Nguyen - Sr Technical Recruiter at Zip | The Org",
            "url": "https://theorg.com/org/ziphq/org-chart/andre-nguyen",
            "description": "Currently serving as a Sr Technical Recruiter at Zip.",
        }

        result = _parse_public_people_result(item, "Zip")

        assert result is not None
        assert result["full_name"] == "Andre Nguyen"
        assert result["profile_data"]["public_identity_slug"] == "ziphq"
        assert result["profile_data"]["public_page_type"] == "org_chart_person"

    def test_parse_public_people_result_rejects_directory_style_titles(self):
        item = {
            "title": "Courtney Cronin's Email & Phone - Zip Staff Directory",
            "url": "https://www.contactout.com/courtney",
            "description": "Staff directory and contact information for Zip.",
        }

        assert _parse_public_people_result(item, "Zip") is None

    async def test_search_public_people_includes_public_identity_terms(self):
        mock_client = _mock_client_with(_mock_httpx_response({"web": {"results": []}}))

        with (
            patch("app.clients.brave_search_client.httpx.AsyncClient", return_value=mock_client),
            patch("app.clients.brave_search_client.settings") as s,
        ):
            s.brave_api_key = "key"
            await search_public_people(
                "Zip",
                titles=["technical recruiter"],
                public_identity_terms=["ziphq"],
            )

        query = mock_client.get.call_args[1]["params"]["q"]
        assert '"Zip"' in query
        assert '"ziphq"' in query


class TestParseHiringTeamResult:
    """Tests for _parse_hiring_team_result() — extracting hiring team from job pages."""

    def test_extracts_posted_by_name(self):
        item = {
            "title": "Senior Engineer at Stripe",
            "url": "https://linkedin.com/jobs/view/123",
            "description": "Great opportunity! Posted by Jane Smith. Apply now.",
        }
        results = _parse_hiring_team_result(item, "Stripe")
        assert len(results) == 1
        assert results[0]["full_name"] == "Jane Smith"
        assert results[0]["source"] == "brave_hiring_team"

    def test_extracts_hiring_manager(self):
        item = {
            "title": "Backend Engineer at Stripe",
            "url": "https://linkedin.com/jobs/view/456",
            "description": "Hiring manager: John Doe for the payments team.",
        }
        results = _parse_hiring_team_result(item, "Stripe")
        assert len(results) == 1
        assert results[0]["full_name"] == "John Doe"

    def test_extracts_linkedin_profile_urls(self):
        item = {
            "title": "Engineer at Stripe",
            "url": "https://linkedin.com/jobs/view/789",
            "description": "Meet our team: https://www.linkedin.com/in/jane-doe",
        }
        results = _parse_hiring_team_result(item, "Stripe")
        assert len(results) == 1
        assert results[0]["linkedin_url"] == "https://www.linkedin.com/in/jane-doe"

    def test_returns_empty_when_no_names(self):
        item = {
            "title": "Engineer at Stripe",
            "url": "https://linkedin.com/jobs/view/000",
            "description": "Great job opportunity at Stripe. Apply now!",
        }
        results = _parse_hiring_team_result(item, "Stripe")
        assert results == []

    def test_returns_empty_for_empty_description(self):
        item = {"title": "Job", "url": "https://linkedin.com/jobs/view/1", "description": ""}
        results = _parse_hiring_team_result(item, "Stripe")
        assert results == []


class TestSearchHiringTeam:
    """Tests for search_hiring_team() — LinkedIn job page search."""

    async def test_query_uses_jobs_site(self):
        mock_client = _mock_client_with(_mock_httpx_response({"web": {"results": []}}))

        with (
            patch("app.clients.brave_search_client.httpx.AsyncClient", return_value=mock_client),
            patch("app.clients.brave_search_client.settings") as s,
        ):
            s.brave_api_key = "key"
            await search_hiring_team("Stripe", "Senior Engineer")

        query = mock_client.get.call_args[1]["params"]["q"]
        assert "site:linkedin.com/jobs" in query
        assert '"Stripe"' in query
        assert '"Senior Engineer"' in query

    async def test_returns_empty_without_api_key(self):
        with patch("app.clients.brave_search_client.settings") as s:
            s.brave_api_key = ""
            results = await search_hiring_team("Stripe", "Engineer")
        assert results == []

    async def test_includes_team_keyword_in_query(self):
        mock_client = _mock_client_with(_mock_httpx_response({"web": {"results": []}}))

        with (
            patch("app.clients.brave_search_client.httpx.AsyncClient", return_value=mock_client),
            patch("app.clients.brave_search_client.settings") as s,
        ):
            s.brave_api_key = "key"
            await search_hiring_team("Stripe", "Engineer", team_keywords=["payments"])

        query = mock_client.get.call_args[1]["params"]["q"]
        assert '"payments"' in query

    async def test_returns_parsed_hiring_team(self):
        mock_resp = _mock_httpx_response({
            "web": {
                "results": [
                    {
                        "title": "Senior Engineer at Stripe",
                        "url": "https://linkedin.com/jobs/view/123",
                        "description": "Posted by Jane Smith for the payments team.",
                    },
                ]
            }
        })
        mock_client = _mock_client_with(mock_resp)

        with (
            patch("app.clients.brave_search_client.httpx.AsyncClient", return_value=mock_client),
            patch("app.clients.brave_search_client.settings") as s,
        ):
            s.brave_api_key = "key"
            results = await search_hiring_team("Stripe", "Senior Engineer")

        assert len(results) == 1
        assert results[0]["full_name"] == "Jane Smith"
        assert results[0]["source"] == "brave_hiring_team"
