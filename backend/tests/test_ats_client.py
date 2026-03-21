"""Unit tests for ATS public board clients."""

import pytest
from unittest.mock import patch, AsyncMock, MagicMock

from app.clients.ats_client import (
    parse_ats_job_url,
    search_ashby,
    search_greenhouse,
    search_lever,
    search_workable,
)

pytestmark = pytest.mark.asyncio


def _mock_httpx_response(json_data, status_code=200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data
    return resp


def _mock_client_with(response):
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=response)
    return mock_client


class TestSearchGreenhouse:
    async def test_returns_full_board_by_default(self):
        jobs = [
            {
                "id": index,
                "title": f"Role {index}",
                "absolute_url": f"https://example.com/{index}",
                "location": {"name": "Remote"},
                "content": f"Description {index}",
                "updated_at": "2026-03-18",
            }
            for index in range(25)
        ]
        mock_client = _mock_client_with(
            _mock_httpx_response({"name": "Affirm", "jobs": jobs})
        )

        with patch("app.clients.ats_client.httpx.AsyncClient", return_value=mock_client):
            results = await search_greenhouse("affirm")

        assert len(results) == 25
        assert results[-1]["title"] == "Role 24"

    async def test_applies_explicit_limit_after_normalization(self):
        jobs = [
            {
                "id": index,
                "title": f"Role {index}",
                "absolute_url": f"https://example.com/{index}",
                "location": {"name": "Remote"},
                "content": f"Description {index}",
                "updated_at": "2026-03-18",
            }
            for index in range(10)
        ]
        mock_client = _mock_client_with(
            _mock_httpx_response({"name": "Affirm", "jobs": jobs})
        )

        with patch("app.clients.ats_client.httpx.AsyncClient", return_value=mock_client):
            results = await search_greenhouse("affirm", limit=3)

        assert len(results) == 3
        assert results[2]["title"] == "Role 2"


class TestSearchLever:
    async def test_returns_full_board_by_default(self):
        postings = [
            {
                "id": f"lever-{index}",
                "text": f"Role {index}",
                "hostedUrl": f"https://example.com/{index}",
                "descriptionPlain": f"Description {index}",
                "categories": {"location": "Remote", "department": "Engineering"},
            }
            for index in range(25)
        ]
        mock_client = _mock_client_with(_mock_httpx_response(postings))

        with patch("app.clients.ats_client.httpx.AsyncClient", return_value=mock_client):
            results = await search_lever("affirm")

        assert len(results) == 25
        assert results[-1]["title"] == "Role 24"


class TestSearchAshby:
    async def test_returns_full_board_by_default(self):
        jobs = [
            {
                "id": f"ashby-{index}",
                "title": f"Role {index}",
                "jobUrl": f"https://example.com/{index}",
                "descriptionPlain": f"Description {index}",
                "location": "Remote",
                "department": "Engineering",
                "publishedAt": "2026-03-18",
            }
            for index in range(25)
        ]
        mock_client = _mock_client_with(
            _mock_httpx_response({"organizationName": "Affirm", "jobs": jobs})
        )

        with patch("app.clients.ats_client.httpx.AsyncClient", return_value=mock_client):
            results = await search_ashby("affirm")

        assert len(results) == 25
        assert results[-1]["title"] == "Role 24"


class TestSearchWorkable:
    async def test_fetches_exact_job_from_public_endpoint(self):
        job_response = _mock_httpx_response(
            {
                "id": 5128536,
                "shortcode": "11DC4EA360",
                "title": "Software Engineer - Early Career (USA)",
                "remote": False,
                "location": {
                    "country": "United States",
                    "city": "Stamford",
                    "region": "Connecticut",
                },
                "locations": [],
                "published": "2025-09-09T00:00:00.000Z",
                "type": "full",
                "department": ["Technology"],
                "workplace": "on_site",
                "description": "<p>Build systems</p>",
            }
        )
        account_response = _mock_httpx_response({"name": "Trexquant Investment"})
        mock_client = _mock_client_with(job_response)
        mock_client.get = AsyncMock(side_effect=[job_response, account_response])

        with patch("app.clients.ats_client.httpx.AsyncClient", return_value=mock_client):
            results = await search_workable("trexquant", job_shortcode="AC6E22F084")

        assert len(results) == 1
        assert results[0]["external_id"] == "wk_11DC4EA360"
        assert results[0]["company_name"] == "Trexquant Investment"
        assert results[0]["url"] == "https://apply.workable.com/trexquant/j/11DC4EA360"
        assert results[0]["location"] == "Stamford, Connecticut, United States"
        assert results[0]["department"] == "Technology"


class TestParseATSJobURL:
    def test_parses_greenhouse_canonical_url(self):
        parsed = parse_ats_job_url("https://job-boards.greenhouse.io/affirm/jobs/7550577003")
        assert parsed is not None
        assert parsed.ats_type == "greenhouse"
        assert parsed.company_slug == "affirm"
        assert parsed.external_id == "gh_7550577003"

    def test_parses_greenhouse_embed_url(self):
        parsed = parse_ats_job_url(
            "https://job-boards.greenhouse.io/embed/job_app?for=affirm&jr_id=foo&token=7550577003"
        )
        assert parsed is not None
        assert parsed.ats_type == "greenhouse"
        assert parsed.company_slug == "affirm"
        assert parsed.external_id == "gh_7550577003"
        assert parsed.canonical_url == "https://job-boards.greenhouse.io/affirm/jobs/7550577003"

    def test_parses_lever_url(self):
        parsed = parse_ats_job_url("https://jobs.lever.co/stripe/abc123")
        assert parsed is not None
        assert parsed.ats_type == "lever"
        assert parsed.company_slug == "stripe"
        assert parsed.external_id == "lv_abc123"

    def test_parses_ashby_url(self):
        parsed = parse_ats_job_url("https://jobs.ashbyhq.com/notion/1234")
        assert parsed is not None
        assert parsed.ats_type == "ashby"
        assert parsed.company_slug == "notion"
        assert parsed.external_id == "ab_1234"

    def test_parses_workable_url(self):
        parsed = parse_ats_job_url("https://apply.workable.com/trexquant/j/AC6E22F084/?jr_id=68c040328e65e77df55bf6c3")
        assert parsed is not None
        assert parsed.ats_type == "workable"
        assert parsed.company_slug == "trexquant"
        assert parsed.external_id == "wk_AC6E22F084"
        assert parsed.canonical_url == "https://apply.workable.com/trexquant/j/AC6E22F084"
