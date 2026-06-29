"""Tests for the per-source timeout safety net in job search.

A single slow/hung aggregator used to hold the whole ``asyncio.gather`` (and the
interactive ``POST /api/jobs/search`` request) open indefinitely. Each source is
now capped by ``constants.SOURCE_FETCH_TIMEOUT_SECONDS`` and fails soft on
timeout instead of stalling every other source.
"""

import asyncio
from unittest.mock import patch

import pytest

from app.services.jobs import constants, search

pytestmark = pytest.mark.asyncio


async def test_hung_source_times_out_and_fails_soft():
    """A source that exceeds the cap returns [] with a 'timeout' failed stat."""

    async def _hang(*args, **kwargs):
        await asyncio.sleep(5)
        return [{"title": "never returned"}]

    with patch.object(constants, "SOURCE_FETCH_TIMEOUT_SECONDS", 0.05), patch.object(
        search, "_dispatch_source_fetch", side_effect=_hang
    ):
        jobs, stat = await search._fetch_jobs_for_source(
            "jsearch",
            query="software engineer",
            location=None,
            remote_only=False,
            limit=20,
        )

    assert jobs == []
    assert stat["status"] == "failed"
    assert stat["error"] == "timeout"


async def test_fast_source_returns_results_within_cap():
    """A source that returns promptly is unaffected by the timeout wrapper."""

    async def _ok(*args, **kwargs):
        return [{"title": "Backend Engineer", "company_name": "Acme"}]

    with patch.object(search, "_dispatch_source_fetch", side_effect=_ok):
        jobs, stat = await search._fetch_jobs_for_source(
            "jsearch",
            query="software engineer",
            location=None,
            remote_only=False,
            limit=20,
        )

    assert len(jobs) == 1
    assert jobs[0]["_fetch_source_key"] == "jsearch"
    assert stat["status"] == "success"
    assert stat["raw_count"] == 1


async def test_newgrad_interactive_fetch_is_capped_to_limit():
    """Interactive newgrad fetch passes ``limit`` so it can't enrich 500 pages."""
    captured: dict = {}

    async def _capture(*args, **kwargs):
        captured.update(kwargs)
        return []

    with patch.object(
        search.newgrad_jobs_client, "search_newgrad_jobs", side_effect=_capture
    ):
        await search._dispatch_source_fetch(
            "newgrad",
            query="software engineer",
            location=None,
            remote_only=False,
            limit=20,
            occupation=None,
        )

    assert captured.get("limit") == 20
