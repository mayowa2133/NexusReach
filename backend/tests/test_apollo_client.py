"""Unit tests for Apollo.io API client — free discovery + on-demand enrichment."""

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


class TestSearchPeople:
    """Tests for search_people() — free api_search endpoint."""

    async def test_calls_free_api_search_endpoint(self):
        """search_people() uses /api/v1/mixed_people/api_search, not /v1/mixed_people/search."""
        mock_resp = _mock_httpx_response({"people": []})
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_resp)

        with (
            patch("app.clients.apollo_client.httpx.AsyncClient", return_value=mock_client),
            patch("app.clients.apollo_client.settings") as mock_settings,
        ):
            mock_settings.apollo_master_api_key = "master-key-123"
            mock_settings.apollo_api_key = "standard-key-456"
            await apollo_client.search_people("Stripe")

        call_args = mock_client.post.call_args
        url = call_args[0][0]
        assert "/api/v1/mixed_people/api_search" in url
        assert "/v1/mixed_people/search" not in url or "/api/v1/" in url

    async def test_sends_master_key_in_header(self):
        """search_people() sends the master API key in X-Api-Key header, not in body."""
        mock_resp = _mock_httpx_response({"people": []})
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_resp)

        with (
            patch("app.clients.apollo_client.httpx.AsyncClient", return_value=mock_client),
            patch("app.clients.apollo_client.settings") as mock_settings,
        ):
            mock_settings.apollo_master_api_key = "master-key-123"
            mock_settings.apollo_api_key = "standard-key-456"
            await apollo_client.search_people("Stripe")

        call_args = mock_client.post.call_args
        headers = call_args[1].get("headers", {})
        json_body = call_args[1].get("json", {})

        assert headers.get("X-Api-Key") == "master-key-123"
        assert "api_key" not in json_body

    async def test_does_not_return_work_email(self):
        """search_people() results do NOT include work_email."""
        mock_resp = _mock_httpx_response({
            "people": [
                {
                    "id": "apollo-123",
                    "name": "Jane Doe",
                    "title": "Software Engineer",
                    "seniority": "senior",
                    "linkedin_url": "https://linkedin.com/in/janedoe",
                    "photo_url": "https://example.com/photo.jpg",
                    "departments": ["engineering_technical"],
                    "organization": {"name": "Stripe"},
                }
            ]
        })
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_resp)

        with (
            patch("app.clients.apollo_client.httpx.AsyncClient", return_value=mock_client),
            patch("app.clients.apollo_client.settings") as mock_settings,
        ):
            mock_settings.apollo_master_api_key = "master-key-123"
            mock_settings.apollo_api_key = ""
            results = await apollo_client.search_people("Stripe")

        assert len(results) == 1
        person = results[0]
        assert "work_email" not in person
        assert "email_verified" not in person

    async def test_returns_apollo_id(self):
        """search_people() returns apollo_id from the response."""
        mock_resp = _mock_httpx_response({
            "people": [
                {
                    "id": "apollo-abc-123",
                    "name": "John Smith",
                    "title": "Engineer",
                    "organization": {"name": "Stripe"},
                }
            ]
        })
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_resp)

        with (
            patch("app.clients.apollo_client.httpx.AsyncClient", return_value=mock_client),
            patch("app.clients.apollo_client.settings") as mock_settings,
        ):
            mock_settings.apollo_master_api_key = "key"
            mock_settings.apollo_api_key = ""
            results = await apollo_client.search_people("Stripe")

        assert results[0]["apollo_id"] == "apollo-abc-123"

    async def test_returns_empty_when_no_key(self):
        """search_people() returns empty list when no API key configured."""
        with patch("app.clients.apollo_client.settings") as mock_settings:
            mock_settings.apollo_master_api_key = ""
            mock_settings.apollo_api_key = ""
            results = await apollo_client.search_people("Stripe")

        assert results == []

    async def test_falls_back_to_standard_key(self):
        """search_people() uses apollo_api_key if master key is not set."""
        mock_resp = _mock_httpx_response({"people": []})
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_resp)

        with (
            patch("app.clients.apollo_client.httpx.AsyncClient", return_value=mock_client),
            patch("app.clients.apollo_client.settings") as mock_settings,
        ):
            mock_settings.apollo_master_api_key = ""
            mock_settings.apollo_api_key = "standard-key-456"
            await apollo_client.search_people("Stripe")

        call_args = mock_client.post.call_args
        headers = call_args[1].get("headers", {})
        assert headers.get("X-Api-Key") == "standard-key-456"


class TestEnrichPerson:
    """Tests for enrich_person() — credit-consuming enrichment."""

    async def test_calls_people_match_endpoint(self):
        """enrich_person() uses /v1/people/match."""
        mock_resp = _mock_httpx_response({
            "person": {
                "id": "apollo-123",
                "email": "jane@stripe.com",
                "email_status": "verified",
            }
        })
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_resp)

        with (
            patch("app.clients.apollo_client.httpx.AsyncClient", return_value=mock_client),
            patch("app.clients.apollo_client.settings") as mock_settings,
        ):
            mock_settings.apollo_api_key = "standard-key"
            await apollo_client.enrich_person(apollo_id="apollo-123")

        call_args = mock_client.post.call_args
        url = call_args[0][0]
        assert "/v1/people/match" in url

    async def test_uses_standard_key_in_body(self):
        """enrich_person() sends standard API key in JSON body, not headers."""
        mock_resp = _mock_httpx_response({
            "person": {
                "id": "apollo-123",
                "email": "jane@stripe.com",
                "email_status": "verified",
            }
        })
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_resp)

        with (
            patch("app.clients.apollo_client.httpx.AsyncClient", return_value=mock_client),
            patch("app.clients.apollo_client.settings") as mock_settings,
        ):
            mock_settings.apollo_api_key = "standard-key-789"
            await apollo_client.enrich_person(apollo_id="apollo-123")

        call_args = mock_client.post.call_args
        json_body = call_args[1].get("json", {})
        assert json_body["api_key"] == "standard-key-789"

    async def test_returns_email_and_verification(self):
        """enrich_person() returns work_email and email_verified."""
        mock_resp = _mock_httpx_response({
            "person": {
                "id": "apollo-123",
                "email": "jane@stripe.com",
                "email_status": "verified",
            }
        })
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_resp)

        with (
            patch("app.clients.apollo_client.httpx.AsyncClient", return_value=mock_client),
            patch("app.clients.apollo_client.settings") as mock_settings,
        ):
            mock_settings.apollo_api_key = "key"
            result = await apollo_client.enrich_person(apollo_id="apollo-123")

        assert result is not None
        assert result["work_email"] == "jane@stripe.com"
        assert result["email_verified"] is True
        assert result["apollo_id"] == "apollo-123"

    async def test_returns_none_when_no_email(self):
        """enrich_person() returns None when person has no email."""
        mock_resp = _mock_httpx_response({
            "person": {
                "id": "apollo-123",
                "email": "",
                "email_status": None,
            }
        })
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_resp)

        with (
            patch("app.clients.apollo_client.httpx.AsyncClient", return_value=mock_client),
            patch("app.clients.apollo_client.settings") as mock_settings,
        ):
            mock_settings.apollo_api_key = "key"
            result = await apollo_client.enrich_person(apollo_id="apollo-123")

        assert result is None

    async def test_returns_none_when_no_match(self):
        """enrich_person() returns None when no person found."""
        mock_resp = _mock_httpx_response({"person": None})
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_resp)

        with (
            patch("app.clients.apollo_client.httpx.AsyncClient", return_value=mock_client),
            patch("app.clients.apollo_client.settings") as mock_settings,
        ):
            mock_settings.apollo_api_key = "key"
            result = await apollo_client.enrich_person(linkedin_url="https://linkedin.com/in/nobody")

        assert result is None

    async def test_returns_none_when_no_key(self):
        """enrich_person() returns None when no API key configured."""
        with patch("app.clients.apollo_client.settings") as mock_settings:
            mock_settings.apollo_api_key = ""
            result = await apollo_client.enrich_person(apollo_id="abc")

        assert result is None

    async def test_returns_none_when_no_identifiers(self):
        """enrich_person() returns None when no identifiers provided."""
        with patch("app.clients.apollo_client.settings") as mock_settings:
            mock_settings.apollo_api_key = "key"
            result = await apollo_client.enrich_person()

        assert result is None

    async def test_enriches_by_linkedin_url(self):
        """enrich_person() can enrich using LinkedIn URL."""
        mock_resp = _mock_httpx_response({
            "person": {
                "id": "apollo-456",
                "email": "john@google.com",
                "email_status": "guessed",
            }
        })
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_resp)

        with (
            patch("app.clients.apollo_client.httpx.AsyncClient", return_value=mock_client),
            patch("app.clients.apollo_client.settings") as mock_settings,
        ):
            mock_settings.apollo_api_key = "key"
            result = await apollo_client.enrich_person(
                linkedin_url="https://linkedin.com/in/johndoe"
            )

        assert result is not None
        assert result["work_email"] == "john@google.com"
        assert result["email_verified"] is False  # "guessed" != "verified"

    async def test_enriches_by_name_and_domain(self):
        """enrich_person() can enrich using name + domain."""
        mock_resp = _mock_httpx_response({
            "person": {
                "id": "apollo-789",
                "email": "alice@meta.com",
                "email_status": "verified",
            }
        })
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_resp)

        with (
            patch("app.clients.apollo_client.httpx.AsyncClient", return_value=mock_client),
            patch("app.clients.apollo_client.settings") as mock_settings,
        ):
            mock_settings.apollo_api_key = "key"
            result = await apollo_client.enrich_person(
                full_name="Alice Johnson", domain="meta.com"
            )

        call_args = mock_client.post.call_args
        json_body = call_args[1].get("json", {})
        assert json_body["first_name"] == "Alice"
        assert json_body["last_name"] == "Johnson"
        assert json_body["domain"] == "meta.com"
        assert result is not None
        assert result["work_email"] == "alice@meta.com"
