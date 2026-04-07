"""Tests for proprietary career-site clients (Amazon, Microsoft, Apple)."""

import pytest

from app.clients.amazon_client import _parse_posted_date, search_amazon_jobs
from app.clients.apple_client import (
    _join_locations,
    _parse_date as apple_parse_date,
    _slugify,
    search_apple_jobs,
)
from app.clients.microsoft_client import (
    _extract_location,
    _is_remote,
    _parse_date as ms_parse_date,
    search_microsoft_jobs,
)

pytestmark = pytest.mark.asyncio


# ---------- Amazon ----------


class TestAmazonParsing:
    def test_parses_standard_date(self):
        assert _parse_posted_date("January 9, 2026") is not None
        assert _parse_posted_date("January 9, 2026").startswith("2026-01-09")

    def test_parses_other_months(self):
        assert _parse_posted_date("March 15, 2026").startswith("2026-03-15")
        assert _parse_posted_date("December 1, 2025").startswith("2025-12-01")

    def test_returns_none_for_empty(self):
        assert _parse_posted_date("") is None
        assert _parse_posted_date(None) is None

    def test_returns_none_for_invalid(self):
        assert _parse_posted_date("not a date") is None


async def test_amazon_search_handles_failure(monkeypatch):
    """search_amazon_jobs returns empty list on HTTP error."""
    import httpx

    class _FailClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            pass

        async def get(self, *a, **kw):
            raise httpx.ConnectError("offline")

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: _FailClient())
    result = await search_amazon_jobs(search_text="engineer", limit=5)
    assert result == []


# ---------- Microsoft ----------


class TestMicrosoftParsing:
    def test_parses_iso_date(self):
        assert ms_parse_date("2026-03-15") is not None
        assert ms_parse_date("2026-03-15").startswith("2026-03-15")

    def test_parses_iso_datetime(self):
        assert ms_parse_date("2026-03-15T12:00:00Z").startswith("2026-03-15")

    def test_returns_none_for_empty(self):
        assert ms_parse_date("") is None
        assert ms_parse_date(None) is None

    def test_extract_location_from_list_of_dicts(self):
        job = {"locations": [{"displayName": "Seattle, WA"}, {"displayName": "Remote"}]}
        assert _extract_location(job) == "Seattle, WA; Remote"

    def test_extract_location_from_flat(self):
        job = {"location": "Redmond, WA"}
        assert _extract_location(job) == "Redmond, WA"

    def test_is_remote_from_location(self):
        assert _is_remote({}, "Remote - US") is True
        assert _is_remote({"title": "Engineer"}, "Seattle, WA") is False

    def test_is_remote_from_work_mode(self):
        job = {"properties": {"workSiteFlexibility": "Remote"}}
        assert _is_remote(job, "Seattle") is True


async def test_microsoft_search_handles_failure(monkeypatch):
    """search_microsoft_jobs returns empty list on HTTP error."""
    import httpx

    class _FailClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            pass

        async def post(self, *a, **kw):
            raise httpx.ConnectError("offline")

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: _FailClient())
    result = await search_microsoft_jobs(search_text="engineer", limit=5)
    assert result == []


# ---------- Apple ----------


class TestAppleParsing:
    def test_slugify(self):
        assert _slugify("Software Engineer") == "software-engineer"
        assert _slugify("Sr. iOS Developer") == "sr-ios-developer"

    def test_join_locations(self):
        locs = [{"name": "Cupertino, CA"}, {"name": "Austin, TX"}]
        assert _join_locations(locs) == "Cupertino, CA; Austin, TX"

    def test_join_locations_deduplicates(self):
        locs = [{"name": "Remote"}, {"name": "Remote"}]
        assert _join_locations(locs) == "Remote"

    def test_parse_date_iso(self):
        assert apple_parse_date("2026-04-01T00:00:00.000Z").startswith("2026-04-01")

    def test_parse_date_plain(self):
        assert apple_parse_date("2026-04-01").startswith("2026-04-01")

    def test_parse_date_none(self):
        assert apple_parse_date(None) is None
        assert apple_parse_date("") is None


async def test_apple_search_handles_failure(monkeypatch):
    """search_apple_jobs returns empty list on HTTP error."""
    import httpx

    class _FailClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            pass

        async def post(self, *a, **kw):
            raise httpx.ConnectError("offline")

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: _FailClient())
    result = await search_apple_jobs(search_text="engineer", limit=5)
    assert result == []
