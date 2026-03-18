"""Unit tests for Hunter client pattern-learning behavior."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.clients import hunter_client

pytestmark = pytest.mark.asyncio


def _mock_httpx_response(json_data, status_code=200):
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = json_data
    response.raise_for_status = MagicMock()
    return response


def _mock_client_with(response):
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=response)
    return mock_client


class TestDomainSearch:
    async def test_parses_explicit_pattern_metadata(self):
        mock_client = _mock_client_with(_mock_httpx_response({
            "data": {
                "pattern": "{first}.{last}",
                "accept_all": True,
                "emails": [],
            }
        }))

        with (
            patch("app.clients.hunter_client.httpx.AsyncClient", return_value=mock_client),
            patch("app.clients.hunter_client.settings") as mock_settings,
        ):
            mock_settings.hunter_api_key = "hunter-key"
            result = await hunter_client.domain_search("affirm.com")

        assert result["pattern"] == "first.last"
        assert result["accept_all"] is True
        assert result["emails"] == []

    async def test_returns_sample_emails_for_pattern_inference(self):
        mock_client = _mock_client_with(_mock_httpx_response({
            "data": {
                "pattern": None,
                "accept_all": False,
                "emails": [
                    {
                        "value": "alex.lee@affirm.com",
                        "first_name": "Alex",
                        "last_name": "Lee",
                        "confidence": 90,
                        "type": "personal",
                    }
                ],
            }
        }))

        with (
            patch("app.clients.hunter_client.httpx.AsyncClient", return_value=mock_client),
            patch("app.clients.hunter_client.settings") as mock_settings,
        ):
            mock_settings.hunter_api_key = "hunter-key"
            result = await hunter_client.domain_search("affirm.com")

        assert result["pattern"] is None
        assert result["emails"][0]["email"] == "alex.lee@affirm.com"
        assert result["emails"][0]["first_name"] == "Alex"
        assert result["emails"][0]["last_name"] == "Lee"

    async def test_handles_partial_payloads_without_crashing(self):
        mock_client = _mock_client_with(_mock_httpx_response({"data": {}}))

        with (
            patch("app.clients.hunter_client.httpx.AsyncClient", return_value=mock_client),
            patch("app.clients.hunter_client.settings") as mock_settings,
        ):
            mock_settings.hunter_api_key = "hunter-key"
            result = await hunter_client.domain_search("affirm.com")

        assert result == {"pattern": None, "accept_all": None, "emails": []}
