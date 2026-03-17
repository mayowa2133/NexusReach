"""Unit tests for Apollo.io API client — free-tier company endpoints + paid people search."""

import pytest
from unittest.mock import patch, AsyncMock, MagicMock

from app.clients import apollo_client

pytestmark = pytest.mark.asyncio


def _mock_httpx_response(json_data, status_code=200):
    """Create a mock httpx response."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.raise_for_status = MagicMock()
    return resp


def _mock_httpx_403():
    """Create a mock 403 response that raises on raise_for_status."""
    import httpx
    resp = MagicMock()
    resp.status_code = 403
    resp.raise_for_status.side_effect = httpx.HTTPStatusError(
        "403 Forbidden", request=MagicMock(), response=resp
    )
    return resp


def _mock_client_with(response):
    """Create a mock httpx.AsyncClient that returns the given response."""
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=response)
    mock_client.get = AsyncMock(return_value=response)
    return mock_client


class TestSearchPeople:
    """Tests for search_people() — paid people discovery (kept for future upgrade)."""

    async def test_calls_api_search_endpoint(self):
        mock_client = _mock_client_with(_mock_httpx_response({"people": []}))

        with (
            patch("app.clients.apollo_client.httpx.AsyncClient", return_value=mock_client),
            patch("app.clients.apollo_client.settings") as s,
        ):
            s.apollo_master_api_key = "master-key"
            s.apollo_api_key = "std-key"
            await apollo_client.search_people("Stripe")

        url = mock_client.post.call_args[0][0]
        assert "/api/v1/mixed_people/api_search" in url

    async def test_sends_key_in_header(self):
        mock_client = _mock_client_with(_mock_httpx_response({"people": []}))

        with (
            patch("app.clients.apollo_client.httpx.AsyncClient", return_value=mock_client),
            patch("app.clients.apollo_client.settings") as s,
        ):
            s.apollo_master_api_key = "master-key"
            s.apollo_api_key = "std-key"
            await apollo_client.search_people("Stripe")

        headers = mock_client.post.call_args[1].get("headers", {})
        json_body = mock_client.post.call_args[1].get("json", {})
        assert headers.get("X-Api-Key") == "master-key"
        assert "api_key" not in json_body

    async def test_returns_empty_on_403(self):
        """Free-tier 403 returns empty list instead of raising."""
        mock_client = _mock_client_with(_mock_httpx_response({}, status_code=403))

        with (
            patch("app.clients.apollo_client.httpx.AsyncClient", return_value=mock_client),
            patch("app.clients.apollo_client.settings") as s,
        ):
            s.apollo_master_api_key = "key"
            s.apollo_api_key = ""
            results = await apollo_client.search_people("Stripe")

        assert results == []

    async def test_returns_empty_when_no_key(self):
        with patch("app.clients.apollo_client.settings") as s:
            s.apollo_master_api_key = ""
            s.apollo_api_key = ""
            results = await apollo_client.search_people("Stripe")
        assert results == []

    async def test_returns_apollo_id(self):
        mock_resp = _mock_httpx_response({
            "people": [{
                "id": "apollo-abc", "name": "Jane", "title": "Eng",
                "organization": {"name": "Stripe"},
            }]
        })
        mock_client = _mock_client_with(mock_resp)

        with (
            patch("app.clients.apollo_client.httpx.AsyncClient", return_value=mock_client),
            patch("app.clients.apollo_client.settings") as s,
        ):
            s.apollo_master_api_key = "key"
            s.apollo_api_key = ""
            results = await apollo_client.search_people("Stripe")

        assert results[0]["apollo_id"] == "apollo-abc"
        assert "work_email" not in results[0]


class TestEnrichPerson:
    """Tests for enrich_person() — paid email enrichment."""

    async def test_returns_email(self):
        mock_resp = _mock_httpx_response({
            "person": {"id": "a123", "email": "j@s.com", "email_status": "verified"}
        })
        mock_client = _mock_client_with(mock_resp)

        with (
            patch("app.clients.apollo_client.httpx.AsyncClient", return_value=mock_client),
            patch("app.clients.apollo_client.settings") as s,
        ):
            s.apollo_api_key = "key"
            result = await apollo_client.enrich_person(apollo_id="a123")

        assert result["work_email"] == "j@s.com"
        assert result["email_verified"] is True

    async def test_returns_none_on_403(self):
        """Free-tier 403 returns None instead of raising."""
        mock_client = _mock_client_with(_mock_httpx_response({}, status_code=403))

        with (
            patch("app.clients.apollo_client.httpx.AsyncClient", return_value=mock_client),
            patch("app.clients.apollo_client.settings") as s,
        ):
            s.apollo_api_key = "key"
            result = await apollo_client.enrich_person(apollo_id="a123")

        assert result is None

    async def test_returns_none_when_no_key(self):
        with patch("app.clients.apollo_client.settings") as s:
            s.apollo_api_key = ""
            result = await apollo_client.enrich_person(apollo_id="abc")
        assert result is None

    async def test_returns_none_when_no_identifiers(self):
        with patch("app.clients.apollo_client.settings") as s:
            s.apollo_api_key = "key"
            result = await apollo_client.enrich_person()
        assert result is None

    async def test_returns_none_when_no_email(self):
        mock_resp = _mock_httpx_response({
            "person": {"id": "a123", "email": "", "email_status": None}
        })
        mock_client = _mock_client_with(mock_resp)

        with (
            patch("app.clients.apollo_client.httpx.AsyncClient", return_value=mock_client),
            patch("app.clients.apollo_client.settings") as s,
        ):
            s.apollo_api_key = "key"
            result = await apollo_client.enrich_person(apollo_id="a123")

        assert result is None


class TestSearchCompany:
    """Tests for search_company() — free-tier organizations/search endpoint."""

    async def test_uses_organizations_search_endpoint(self):
        mock_resp = _mock_httpx_response({
            "organizations": [{"name": "Google", "primary_domain": "google.com",
                               "industry": "tech", "estimated_num_employees": 188000}]
        })
        mock_client = _mock_client_with(mock_resp)

        with (
            patch("app.clients.apollo_client.httpx.AsyncClient", return_value=mock_client),
            patch("app.clients.apollo_client.settings") as s,
        ):
            s.apollo_master_api_key = ""
            s.apollo_api_key = "key"
            result = await apollo_client.search_company("Google")

        url = mock_client.post.call_args[0][0]
        assert "/api/v1/organizations/search" in url
        headers = mock_client.post.call_args[1].get("headers", {})
        assert headers.get("X-Api-Key") == "key"
        assert result["name"] == "Google"
        assert result["domain"] == "google.com"

    async def test_returns_none_when_no_key(self):
        with patch("app.clients.apollo_client.settings") as s:
            s.apollo_master_api_key = ""
            s.apollo_api_key = ""
            result = await apollo_client.search_company("Google")
        assert result is None

    async def test_returns_none_on_empty_results(self):
        mock_client = _mock_client_with(_mock_httpx_response({"organizations": []}))

        with (
            patch("app.clients.apollo_client.httpx.AsyncClient", return_value=mock_client),
            patch("app.clients.apollo_client.settings") as s,
        ):
            s.apollo_master_api_key = ""
            s.apollo_api_key = "key"
            result = await apollo_client.search_company("NonExistentCorp")

        assert result is None


class TestEnrichCompany:
    """Tests for enrich_company() — free-tier organizations/enrich endpoint."""

    async def test_uses_get_with_domain_param(self):
        mock_resp = _mock_httpx_response({
            "organization": {"name": "Stripe", "primary_domain": "stripe.com",
                             "industry": "fintech", "estimated_num_employees": 8000}
        })
        mock_client = _mock_client_with(mock_resp)

        with (
            patch("app.clients.apollo_client.httpx.AsyncClient", return_value=mock_client),
            patch("app.clients.apollo_client.settings") as s,
        ):
            s.apollo_master_api_key = ""
            s.apollo_api_key = "key"
            result = await apollo_client.enrich_company("stripe.com")

        url = mock_client.get.call_args[0][0]
        assert "/api/v1/organizations/enrich" in url
        params = mock_client.get.call_args[1].get("params", {})
        assert params["domain"] == "stripe.com"
        assert result["name"] == "Stripe"

    async def test_returns_none_when_no_key(self):
        with patch("app.clients.apollo_client.settings") as s:
            s.apollo_master_api_key = ""
            s.apollo_api_key = ""
            result = await apollo_client.enrich_company("stripe.com")
        assert result is None

    async def test_returns_none_on_no_organization(self):
        mock_client = _mock_client_with(_mock_httpx_response({"organization": None}))

        with (
            patch("app.clients.apollo_client.httpx.AsyncClient", return_value=mock_client),
            patch("app.clients.apollo_client.settings") as s,
        ):
            s.apollo_master_api_key = ""
            s.apollo_api_key = "key"
            result = await apollo_client.enrich_company("nonexistent.xyz")

        assert result is None
