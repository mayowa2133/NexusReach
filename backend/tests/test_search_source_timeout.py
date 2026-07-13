"""Tests for the per-source timeout safety net in job search.

A single slow/hung aggregator used to hold the whole ``asyncio.gather`` (and the
interactive ``POST /api/jobs/search`` request) open indefinitely. Each source is
now capped by ``constants.SOURCE_FETCH_TIMEOUT_SECONDS`` and fails soft on
timeout instead of stalling every other source.
"""

import asyncio
import logging
from unittest.mock import patch

import httpx
import pytest

from app.services.jobs import constants, normalize, search, storage

pytestmark = pytest.mark.asyncio


async def test_is_transient_fetch_error_classification():
    """Network/timeout errors are transient; logic bugs are not."""
    assert normalize.is_transient_fetch_error(httpx.ConnectTimeout("boom"))
    assert normalize.is_transient_fetch_error(httpx.ReadTimeout("boom"))
    assert normalize.is_transient_fetch_error(httpx.ConnectError("boom"))
    assert normalize.is_transient_fetch_error(asyncio.TimeoutError())
    assert normalize.is_transient_fetch_error(ConnectionResetError())
    # Genuine bugs must NOT be classified as transient (they stay Sentry errors).
    assert not normalize.is_transient_fetch_error(ValueError("bad parse"))
    assert not normalize.is_transient_fetch_error(KeyError("missing"))


async def test_connect_timeout_logs_warning_not_exception(caplog):
    """A ConnectTimeout from a source fails soft and logs at WARNING (no Sentry).

    Sentry's logging integration captures ERROR+ records; logging the expected
    third-party connect timeout at WARNING keeps it out of the issue stream.
    """

    async def _boom(*args, **kwargs):
        raise httpx.ConnectTimeout("connection timed out")

    with patch.object(search, "_dispatch_source_fetch", side_effect=_boom):
        with caplog.at_level(logging.WARNING, logger="app.services.jobs.search"):
            jobs, stat = await search._fetch_jobs_for_source(
                "newgrad",
                query="software engineer",
                location=None,
                remote_only=False,
                limit=20,
            )

    assert jobs == []
    assert stat["status"] == "failed"
    # The record must be WARNING, never ERROR (ERROR is what reaches Sentry).
    records = [r for r in caplog.records if "newgrad" in r.getMessage()]
    assert records, "expected a log record mentioning the source"
    assert all(r.levelno == logging.WARNING for r in records)


async def test_real_bug_still_logged_as_error(caplog):
    """A non-network exception still goes through logger.exception (ERROR)."""

    async def _bug(*args, **kwargs):
        raise ValueError("genuine parse bug")

    with patch.object(search, "_dispatch_source_fetch", side_effect=_bug):
        with caplog.at_level(logging.DEBUG, logger="app.services.jobs.search"):
            jobs, stat = await search._fetch_jobs_for_source(
                "jsearch",
                query="software engineer",
                location=None,
                remote_only=False,
                limit=20,
            )

    assert jobs == []
    assert any(r.levelno == logging.ERROR for r in caplog.records)


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


# --- Sustained-outage monitoring (storage.classify_source_health) ---


async def test_classify_flags_sustained_outage_not_transient_blips():
    """A source failing ~100% over many attempts is degraded; a 1-in-N blip isn't."""
    rows = [
        # Matches the real prod pattern: 1 transient failure out of ~1288 runs.
        {"source": "jobicy", "attempts": 1288, "failures": 1, "last_success": "x"},
        # Genuinely down: every attempt in the window failed.
        {"source": "dice", "attempts": 320, "failures": 320, "last_success": None,
         "sample_error": "ConnectTimeout"},
    ]
    out = {
        r["source"]: r
        for r in storage.classify_source_health(
            rows, min_attempts=10, failure_rate_threshold=0.9
        )
    }
    assert out["jobicy"]["degraded"] is False
    assert out["dice"]["degraded"] is True
    assert out["dice"]["failure_rate"] == 1.0
    assert out["jobicy"]["failure_rate"] < 0.01


async def test_classify_requires_minimum_attempts():
    """A source with too few attempts is never flagged, even at 100% failure."""
    rows = [{"source": "usajobs", "attempts": 3, "failures": 3, "last_success": None}]
    out = storage.classify_source_health(
        rows, min_attempts=10, failure_rate_threshold=0.9
    )
    assert out[0]["degraded"] is False


async def test_classify_handles_zero_attempts():
    """No attempts → rate 0.0, not a ZeroDivisionError, not degraded."""
    rows = [{"source": "newgrad", "attempts": 0, "failures": 0}]
    out = storage.classify_source_health(
        rows, min_attempts=10, failure_rate_threshold=0.9
    )
    assert out[0]["failure_rate"] == 0.0
    assert out[0]["degraded"] is False


async def test_usefulness_budget_favors_relevant_complete_source():
    rows = []
    for _ in range(3):
        rows.extend([
            {
                "source": "strong",
                "details": {
                    "requested_occupation": "marketing",
                    "accepted_count": 10,
                    "occupation_rejected_count": 1,
                    "with_description": 10,
                    "with_direct_apply": 10,
                    "with_posted_date": 9,
                    "with_salary": 5,
                    "with_location": 10,
                },
            },
            {
                "source": "noisy",
                "details": {
                    "requested_occupation": "marketing",
                    "accepted_count": 2,
                    "occupation_rejected_count": 8,
                    "with_description": 2,
                    "with_direct_apply": 0,
                    "with_posted_date": 0,
                    "with_salary": 0,
                    "with_location": 1,
                },
            },
        ])

    factors = storage.compute_source_budget_factors(
        rows, occupation_keys=["marketing"]
    )
    limits = storage.source_limits_for_budget(
        ["strong", "noisy", "unseen"], base_limit=20, factors=factors
    )

    assert factors["strong"] > 1.0
    assert factors["noisy"] < 1.0
    assert limits["strong"] > limits["unseen"] > limits["noisy"]


async def test_usefulness_budget_keeps_exploration_until_sample_is_sufficient():
    rows = [{
        "source": "new_source",
        "details": {
            "requested_occupation": "healthcare",
            "accepted_count": 1,
            "occupation_rejected_count": 19,
        },
    }]

    factors = storage.compute_source_budget_factors(
        rows, occupation_keys=["healthcare"]
    )

    assert factors["new_source"] == 1.0


async def test_usefulness_budget_penalizes_stale_invalid_costly_slow_results():
    healthy_rows = []
    degraded_rows = []
    for _ in range(3):
        base = {
            "requested_occupation": "marketing",
            "accepted_count": 10,
            "occupation_rejected_count": 1,
            "with_description": 10,
            "with_direct_apply": 10,
            "with_posted_date": 10,
            "with_salary": 5,
            "with_location": 10,
        }
        healthy_rows.append({
            "source": "healthy",
            "duration_seconds": 1,
            "details": {**base, "direct_apply_valid_count": 10},
        })
        degraded_rows.append({
            "source": "degraded",
            "duration_seconds": 20,
            "details": {
                **base,
                "direct_apply_invalid_count": 10,
                "stale_count": 8,
                "closed_count": 1,
                "estimated_cost_usd": 1.0,
            },
        })

    factors = storage.compute_source_budget_factors(
        healthy_rows + degraded_rows,
        occupation_keys=["marketing"],
    )

    assert factors["healthy"] > factors["degraded"]


async def test_country_and_location_priority_shape_budgets_with_exploration_floor():
    first = storage.source_limits_for_budget(
        ["jobbank", "adzuna", "jsearch"],
        base_limit=20,
        location="Toronto, Canada",
        priority_rank=0,
    )
    third = storage.source_limits_for_budget(
        ["jobbank", "adzuna", "jsearch"],
        base_limit=20,
        location="Toronto, Canada",
        priority_rank=2,
    )

    assert first["jobbank"] > first["adzuna"] > first["jsearch"]
    assert first["jobbank"] > third["jobbank"]
    assert min(third.values()) >= 5


async def test_thread_exhaustion_is_transient():
    """Worker thread-pool exhaustion is operational, not a paged bug (PYTHON-1D/1E)."""
    assert normalize.is_transient_fetch_error(RuntimeError("can't start new thread"))
    # Other RuntimeErrors stay genuine bugs.
    assert not normalize.is_transient_fetch_error(RuntimeError("dict changed size"))
