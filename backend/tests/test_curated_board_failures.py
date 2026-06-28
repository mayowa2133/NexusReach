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
