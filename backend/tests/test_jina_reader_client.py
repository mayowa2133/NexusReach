"""Tests for the Jina Reader public-page fallback client."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.clients import jina_reader_client
from app.config import settings

pytestmark = pytest.mark.asyncio


class _Response:
    def __init__(self, *, payload: object, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def json(self) -> object:
        return self._payload


class _Client:
    def __init__(self, response: _Response | None = None, error: Exception | None = None) -> None:
        self._response = response
        self._error = error
        self.requested_url: str | None = None
        self.requested_headers: dict | None = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url: str, headers: dict | None = None):
        self.requested_url = url
        self.requested_headers = headers
        if self._error:
            raise self._error
        return self._response


async def test_fetch_url_normalizes_json_payload():
    client = _Client(
        _Response(
            payload={
                "code": 200,
                "data": {
                    "title": "Acme — Leadership",
                    "url": "https://acme.com/team",
                    "content": "Jane Doe, VP of Engineering. John Roe, Head of Talent.",
                },
            }
        )
    )
    with (
        patch.object(settings, "jina_reader_enabled", True),
        patch.object(settings, "jina_reader_api_key", ""),
        patch(
            "app.clients.jina_reader_client.is_safe_public_url_async",
            new_callable=AsyncMock,
            return_value=True,
        ),
        patch("app.clients.jina_reader_client.httpx.AsyncClient", return_value=client),
    ):
        page = await jina_reader_client.fetch_url("https://acme.com/team")

    assert page is not None
    assert page["title"] == "Acme — Leadership"
    assert "VP of Engineering" in page["content"]
    assert page["retrieval_method"] == "jina_reader"
    # The readable target URL is prepended, not percent-encoded.
    assert client.requested_url == "https://r.jina.ai/https://acme.com/team"
    assert client.requested_headers["Accept"] == "application/json"
    assert "Authorization" not in client.requested_headers


async def test_fetch_url_sends_bearer_when_key_set():
    client = _Client(
        _Response(payload={"data": {"title": "T", "content": "body text here"}})
    )
    with (
        patch.object(settings, "jina_reader_enabled", True),
        patch.object(settings, "jina_reader_api_key", "secret-key"),
        patch(
            "app.clients.jina_reader_client.is_safe_public_url_async",
            new_callable=AsyncMock,
            return_value=True,
        ),
        patch("app.clients.jina_reader_client.httpx.AsyncClient", return_value=client),
    ):
        page = await jina_reader_client.fetch_url("https://acme.com/team")

    assert page is not None
    assert client.requested_headers["Authorization"] == "Bearer secret-key"


async def test_fetch_url_returns_none_when_disabled():
    with (
        patch.object(settings, "jina_reader_enabled", False),
        patch(
            "app.clients.jina_reader_client.is_safe_public_url_async",
            new_callable=AsyncMock,
            return_value=True,
        ) as safe,
    ):
        page = await jina_reader_client.fetch_url("https://acme.com/team")

    assert page is None
    # Short-circuits before any URL validation / network work.
    safe.assert_not_awaited()


@pytest.mark.parametrize(
    "url",
    [
        "https://www.linkedin.com/in/jane-doe",
        "https://linkedin.com/in/jane-doe",
        "https://ca.linkedin.com/in/jane-doe",
    ],
)
async def test_fetch_url_never_touches_linkedin(url):
    with (
        patch.object(settings, "jina_reader_enabled", True),
        patch(
            "app.clients.jina_reader_client.is_safe_public_url_async",
            new_callable=AsyncMock,
            return_value=True,
        ) as safe,
        patch("app.clients.jina_reader_client.httpx.AsyncClient") as mock_client_cls,
    ):
        page = await jina_reader_client.fetch_url(url)

    assert page is None
    # Guard short-circuits before any URL validation or network work.
    safe.assert_not_awaited()
    mock_client_cls.assert_not_called()


async def test_fetch_url_rejects_unsafe_target():
    with (
        patch.object(settings, "jina_reader_enabled", True),
        patch(
            "app.clients.jina_reader_client.is_safe_public_url_async",
            new_callable=AsyncMock,
            return_value=False,
        ),
        patch("app.clients.jina_reader_client.httpx.AsyncClient") as mock_client_cls,
    ):
        page = await jina_reader_client.fetch_url("http://169.254.169.254/latest/meta-data")

    assert page is None
    mock_client_cls.assert_not_called()


async def test_fetch_url_fails_soft_on_http_error():
    client = _Client(error=httpx.ConnectError("boom"))
    with (
        patch.object(settings, "jina_reader_enabled", True),
        patch(
            "app.clients.jina_reader_client.is_safe_public_url_async",
            new_callable=AsyncMock,
            return_value=True,
        ),
        patch("app.clients.jina_reader_client.httpx.AsyncClient", return_value=client),
    ):
        page = await jina_reader_client.fetch_url("https://acme.com/team")

    assert page is None


async def test_fetch_url_returns_none_on_empty_content():
    client = _Client(_Response(payload={"data": {"title": "T", "content": "   "}}))
    with (
        patch.object(settings, "jina_reader_enabled", True),
        patch(
            "app.clients.jina_reader_client.is_safe_public_url_async",
            new_callable=AsyncMock,
            return_value=True,
        ),
        patch("app.clients.jina_reader_client.httpx.AsyncClient", return_value=client),
    ):
        page = await jina_reader_client.fetch_url("https://acme.com/team")

    assert page is None
