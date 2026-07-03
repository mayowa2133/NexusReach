import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.clients import workday_client
from app.services.jobs.curated_boards import fetch_curated_ats_source_payloads


pytestmark = pytest.mark.asyncio


async def test_search_workday_soft_fails_on_non_json_200():
    """A Workday tenant returning a 200 with a non-JSON body (maintenance /
    anti-bot) must break softly to [], not raise a JSONDecodeError that the
    caller reports to Sentry (regression for PYTHON-V)."""
    resp = MagicMock()
    resp.status_code = 200
    resp.json.side_effect = json.JSONDecodeError("Expecting value", "", 0)

    client = MagicMock()
    client.post = AsyncMock(return_value=resp)
    client.aclose = AsyncMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)

    with patch("app.clients.workday_client.httpx.AsyncClient", return_value=client):
        jobs = await workday_client.search_workday("acme", "wd5", "ext", "Acme")

    assert jobs == []


async def test_fetch_curated_ats_source_payloads_soft_fails_transient_http_errors():
    with (
        patch("app.services.jobs.curated_boards.constants.ATS_DISCOVER_BOARDS", []),
        patch("app.services.jobs.curated_boards.constants.LEVER_DISCOVER_SLUGS", ["greenlight"]),
        patch(
            "app.services.jobs.curated_boards.lever_scrape_client.search_lever_html",
            new=AsyncMock(side_effect=httpx.ReadTimeout("timed out")),
        ),
        patch(
            "app.services.jobs.curated_boards.workday_client.discover_all_workday",
            new=AsyncMock(return_value=[]),
        ),
        patch(
            "app.services.jobs.curated_boards.amazon_client.search_amazon_jobs",
            new=AsyncMock(return_value=[]),
        ),
        patch(
            "app.services.jobs.curated_boards.microsoft_client.search_microsoft_jobs",
            new=AsyncMock(return_value=[]),
        ),
        patch(
            "app.services.jobs.curated_boards.apple_client.search_apple_jobs",
            new=AsyncMock(return_value=[]),
        ),
        patch(
            "app.services.jobs.curated_boards.google_client.search_google_jobs",
            new=AsyncMock(return_value=[]),
        ),
        patch(
            "app.services.jobs.curated_boards.tesla_client.search_tesla_jobs",
            new=AsyncMock(return_value=[]),
        ),
        patch(
            "app.services.jobs.curated_boards.meta_client.search_meta_jobs",
            new=AsyncMock(return_value=[]),
        ),
    ):
        source_payloads, source_stats = await fetch_curated_ats_source_payloads()

    assert source_payloads["lever:greenlight"] == []
    stat = next(item for item in source_stats if item["source"] == "lever:greenlight")
    assert stat["status"] == "failed"
    assert stat["error"].startswith("ReadTimeout:")


async def test_fetch_curated_ats_source_payloads_shares_one_client():
    """Every board fetch in one crawl run must receive the same shared httpx
    client (keep-alive reuse across ~1k boards), and it must be closed after."""
    adapter = MagicMock()
    adapter.search_board = AsyncMock(return_value=[])

    boards = [
        {"ats": "greenhouse", "slug": "acme"},
        {"ats": "ashby", "slug": "globex"},
    ]

    with (
        patch("app.services.jobs.curated_boards.constants.ATS_DISCOVER_BOARDS", boards),
        patch("app.services.jobs.curated_boards.constants.LEVER_DISCOVER_SLUGS", ["greenlight"]),
        patch("app.services.jobs.curated_boards.ats.get_adapter", return_value=adapter),
        patch(
            "app.services.jobs.curated_boards.lever_scrape_client.search_lever_html",
            new=AsyncMock(return_value=[]),
        ) as mock_lever,
        patch(
            "app.services.jobs.curated_boards.workday_client.discover_all_workday",
            new=AsyncMock(return_value=[]),
        ),
        patch(
            "app.services.jobs.curated_boards.amazon_client.search_amazon_jobs",
            new=AsyncMock(return_value=[]),
        ),
        patch(
            "app.services.jobs.curated_boards.microsoft_client.search_microsoft_jobs",
            new=AsyncMock(return_value=[]),
        ),
        patch(
            "app.services.jobs.curated_boards.apple_client.search_apple_jobs",
            new=AsyncMock(return_value=[]),
        ),
        patch(
            "app.services.jobs.curated_boards.google_client.search_google_jobs",
            new=AsyncMock(return_value=[]),
        ),
        patch(
            "app.services.jobs.curated_boards.tesla_client.search_tesla_jobs",
            new=AsyncMock(return_value=[]),
        ),
        patch(
            "app.services.jobs.curated_boards.meta_client.search_meta_jobs",
            new=AsyncMock(return_value=[]),
        ),
    ):
        await fetch_curated_ats_source_payloads()

    clients = [
        call.kwargs.get("client") for call in adapter.search_board.call_args_list
    ] + [call.kwargs.get("client") for call in mock_lever.call_args_list]
    assert len(clients) == 3
    assert all(c is clients[0] for c in clients)
    assert isinstance(clients[0], httpx.AsyncClient)
    assert clients[0].is_closed


async def test_browser_source_runs_after_gather_and_fails_soft():
    """Tesla (Crawl4AI/Chromium) is serialized after the HTTP fan-out but still
    lands in the payloads; a launch failure fails soft as a failed stat, and a
    success is stamped like any other source."""
    with (
        patch("app.services.jobs.curated_boards.constants.ATS_DISCOVER_BOARDS", []),
        patch("app.services.jobs.curated_boards.constants.LEVER_DISCOVER_SLUGS", []),
        patch(
            "app.services.jobs.curated_boards.workday_client.discover_all_workday",
            new=AsyncMock(return_value=[]),
        ),
        patch(
            "app.services.jobs.curated_boards.amazon_client.search_amazon_jobs",
            new=AsyncMock(return_value=[]),
        ),
        patch(
            "app.services.jobs.curated_boards.microsoft_client.search_microsoft_jobs",
            new=AsyncMock(return_value=[]),
        ),
        patch(
            "app.services.jobs.curated_boards.apple_client.search_apple_jobs",
            new=AsyncMock(return_value=[]),
        ),
        patch(
            "app.services.jobs.curated_boards.google_client.search_google_jobs",
            new=AsyncMock(return_value=[]),
        ),
        patch(
            "app.services.jobs.curated_boards.meta_client.search_meta_jobs",
            new=AsyncMock(return_value=[]),
        ),
        patch(
            "app.services.jobs.curated_boards.tesla_client.search_tesla_jobs",
            new=AsyncMock(
                return_value=[
                    {
                        "external_id": "tesla_123",
                        "title": "Software Engineer",
                        "company_name": "Tesla",
                        "url": "https://www.tesla.com/careers/search/job/x-123",
                        "source": "tesla",
                    }
                ]
            ),
        ),
    ):
        source_payloads, source_stats = await fetch_curated_ats_source_payloads()

    assert len(source_payloads["tesla"]) == 1
    assert source_payloads["tesla"][0]["_source_run_key"] == "tesla"
    tesla_stat = next(s for s in source_stats if s["source"] == "tesla")
    assert tesla_stat["status"] == "success"
    assert tesla_stat["raw_count"] == 1
