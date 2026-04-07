"""Tests for proprietary career-site clients (Amazon, Microsoft, Apple, Google, Tesla, Meta)."""

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


# ---------- Google ----------


class TestGoogleParsing:
    def test_strip_tags(self):
        from app.clients.google_client import _strip_tags
        assert _strip_tags("<b>Hello</b> World") == "Hello World"
        assert _strip_tags("Plain text") == "Plain text"

    def test_extract_job_id(self):
        from app.clients.google_client import _extract_job_url
        url = _extract_job_url("https://example.com", "12345")
        assert "12345" in url


async def test_google_search_handles_failure(monkeypatch):
    """search_google_jobs returns empty list on HTTP error."""
    import httpx
    from app.clients.google_client import search_google_jobs

    class _FailClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            pass

        async def get(self, *a, **kw):
            raise httpx.ConnectError("offline")

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: _FailClient())
    result = await search_google_jobs(search_text="engineer", limit=5)
    assert result == []


# ---------- Tesla ----------


async def test_tesla_search_without_crawl4ai(monkeypatch):
    """search_tesla_jobs returns empty list when Crawl4AI is not installed."""
    import builtins
    from app.clients.tesla_client import search_tesla_jobs

    real_import = builtins.__import__

    def _mock_import(name, *args, **kwargs):
        if name == "crawl4ai":
            raise ImportError("crawl4ai not installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _mock_import)
    result = await search_tesla_jobs(search_text="engineer", limit=5)
    assert result == []


class TestTeslaParsing:
    def test_parse_jobs_from_html(self):
        from app.clients.tesla_client import _parse_jobs_from_html
        html = '''
        <a href="/careers/search/job/software-engineer-123456">Software Engineer</a>
        <a href="/careers/search/job/data-scientist-789012">Data Scientist</a>
        '''
        jobs = _parse_jobs_from_html(html)
        assert len(jobs) == 2
        assert jobs[0]["title"] == "Software Engineer"
        assert jobs[0]["company_name"] == "Tesla"
        assert "123456" in jobs[0]["external_id"]

    def test_deduplicates_same_path(self):
        from app.clients.tesla_client import _parse_jobs_from_html
        html = '''
        <a href="/careers/search/job/sw-eng-123">SW Eng</a>
        <a href="/careers/search/job/sw-eng-123">SW Eng</a>
        '''
        jobs = _parse_jobs_from_html(html)
        assert len(jobs) == 1


# ---------- Meta ----------


async def test_meta_search_without_crawl4ai(monkeypatch):
    """search_meta_jobs returns empty list when Crawl4AI is not installed."""
    import builtins
    from app.clients.meta_client import search_meta_jobs

    real_import = builtins.__import__

    def _mock_import(name, *args, **kwargs):
        if name == "crawl4ai":
            raise ImportError("crawl4ai not installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _mock_import)
    result = await search_meta_jobs(search_text="engineer", limit=5)
    assert result == []


class TestMetaParsing:
    def test_parse_jobs_from_structured_data(self):
        from app.clients.meta_client import _parse_jobs_from_html
        html = '''
        {"jobId": "1234567890", "title": "Software Engineer", "location": "Menlo Park, CA"}
        {"jobId": "9876543210", "title": "Data Scientist", "location": "Remote"}
        '''
        jobs = _parse_jobs_from_html(html)
        assert len(jobs) == 2
        assert jobs[0]["title"] == "Software Engineer"
        assert jobs[0]["company_name"] == "Meta"
        assert jobs[0]["location"] == "Menlo Park, CA"
        assert jobs[1]["remote"] is True

    def test_deduplicates_same_id(self):
        from app.clients.meta_client import _parse_jobs_from_html
        html = '''
        {"jobId": "111", "title": "SWE"} {"jobId": "111", "title": "SWE"}
        '''
        jobs = _parse_jobs_from_html(html)
        assert len(jobs) == 1
