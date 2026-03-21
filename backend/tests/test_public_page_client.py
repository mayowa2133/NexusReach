"""Tests for generic public page retrieval."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.clients import public_page_client

pytestmark = pytest.mark.asyncio


class _Response:
    def __init__(self, *, text: str, url: str, content_type: str = "text/html") -> None:
        self.text = text
        self.url = url
        self.headers = {"content-type": content_type}

    def raise_for_status(self) -> None:
        return None


class _Client:
    def __init__(self, response: _Response | None = None, error: Exception | None = None) -> None:
        self._response = response
        self._error = error

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url: str, headers: dict | None = None):  # noqa: ARG002
        if self._error:
            raise self._error
        return self._response


async def test_fetch_direct_page_extracts_title_and_text():
    html = "<html><head><title>Zip</title></head><body><h1>Alicia Zhou</h1><p>Engineering Manager at Zip</p></body></html>"

    with patch(
        "app.clients.public_page_client.httpx.AsyncClient",
        return_value=_Client(response=_Response(text=html, url="https://theorg.com/org/ziphq")),
    ):
        page = await public_page_client.fetch_direct_page("https://theorg.com/org/ziphq")

    assert page is not None
    assert page["title"] == "Zip"
    assert "Engineering Manager at Zip" in page["content"]
    assert page["retrieval_method"] == "direct"


async def test_fetch_page_falls_back_to_crawl4ai_when_direct_fails():
    with (
        patch(
            "app.clients.public_page_client.fetch_direct_page",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "app.clients.public_page_client.crawl4ai_client.fetch_url",
            new_callable=AsyncMock,
            return_value={
                "url": "https://example.com/profile",
                "title": "Example",
                "content": "Currently working at Twitch as an engineer",
                "html": "<html></html>",
                "markdown": "Currently working at Twitch as an engineer",
                "retrieval_method": "crawl4ai",
            },
        ) as mock_crawl4ai,
        patch(
            "app.clients.public_page_client.firecrawl_client.scrape_url",
            new_callable=AsyncMock,
        ) as mock_firecrawl,
    ):
        page = await public_page_client.fetch_page("https://example.com/profile")

    assert page is not None
    assert page["retrieval_method"] == "crawl4ai"
    mock_crawl4ai.assert_awaited_once()
    mock_firecrawl.assert_not_awaited()


async def test_fetch_page_uses_firecrawl_as_optional_last_fallback():
    with (
        patch(
            "app.clients.public_page_client.fetch_direct_page",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "app.clients.public_page_client.crawl4ai_client.fetch_url",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "app.clients.public_page_client.firecrawl_client.scrape_url",
            new_callable=AsyncMock,
            return_value={
                "url": "https://example.com/profile",
                "title": "Example",
                "content": "Currently serving as an Engineering Manager at Twitch since 2022.",
                "html": "<html></html>",
                "markdown": "",
                "retrieval_method": "firecrawl",
            },
        ) as mock_firecrawl,
    ):
        page = await public_page_client.fetch_page("https://example.com/profile")

    assert page is not None
    assert page["retrieval_method"] == "firecrawl"
    mock_firecrawl.assert_awaited_once()


async def test_fetch_page_returns_direct_result_when_fallbacks_fail():
    direct_page = {
        "url": "https://example.com/profile",
        "title": "Example",
        "content": "Short page",
        "html": "<html><body>Short page</body></html>",
        "markdown": "",
        "retrieval_method": "direct",
        "fallback_used": False,
    }
    with (
        patch(
            "app.clients.public_page_client.fetch_direct_page",
            new_callable=AsyncMock,
            return_value=direct_page,
        ),
        patch(
            "app.clients.public_page_client.crawl4ai_client.fetch_url",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "app.clients.public_page_client.firecrawl_client.scrape_url",
            new_callable=AsyncMock,
            return_value=None,
        ),
    ):
        page = await public_page_client.fetch_page("https://example.com/profile")

    assert page == direct_page
