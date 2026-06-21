from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.services.jobs.curated_boards import fetch_curated_ats_source_payloads


pytestmark = pytest.mark.asyncio


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
