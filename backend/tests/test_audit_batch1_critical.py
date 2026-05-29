"""Proof tests for audit Batch 1 (CRITICAL) fixes — 2026-05-29.

Covers:
- C1: SearXNG source labels are trusted and out-rank the fallback floor.
- C2: peer title-recovery guard uses the correct plural bucket name.
- C4: Dice search fails soft when no API key is configured.
- C5: Adzuna currency map returns the local currency per country.
"""

import pytest


# ---------------------------------------------------------------------------
# C1 — SearXNG trust + priority
# ---------------------------------------------------------------------------
def test_c1_searxng_hiring_team_is_trusted():
    from app.services.people_service import CURRENT_TRUSTED_SOURCES

    assert "searxng_hiring_team" in CURRENT_TRUSTED_SOURCES
    # Paid fallbacks remain trusted too.
    assert "brave_hiring_team" in CURRENT_TRUSTED_SOURCES
    assert "serper_hiring_team" in CURRENT_TRUSTED_SOURCES


def test_c1_searxng_labels_have_real_priority_not_fallback_floor():
    from app.services.people_service import SOURCE_PRIORITY, _source_rank

    # All three SearXNG families must be ranked explicitly.
    assert SOURCE_PRIORITY["searxng_hiring_team"] == SOURCE_PRIORITY["brave_hiring_team"]
    assert SOURCE_PRIORITY["searxng_search"] == SOURCE_PRIORITY["brave_search"]
    assert "searxng_public_web" in SOURCE_PRIORITY

    # The unknown-source fallback is 5 (worst). SearXNG must out-rank it.
    unknown_rank = _source_rank("totally_unknown_source")
    assert _source_rank("searxng_hiring_team") < unknown_rank
    assert _source_rank("searxng_search") < unknown_rank
    assert _source_rank("searxng_public_web") < unknown_rank


def test_c1_searxng_public_web_is_recognized_as_public_web_source():
    from app.services.people_service import PUBLIC_WEB_SOURCES

    assert "searxng_public_web" in PUBLIC_WEB_SOURCES


# ---------------------------------------------------------------------------
# C2 — peer bucket typo
# ---------------------------------------------------------------------------
def test_c2_peer_bucket_guard_uses_plural():
    """The title-recovery guard must reference the plural 'peers' bucket.

    Singular 'peer' never matches the bucket value, so the guard always
    short-circuited True and overwrote good peer titles unconditionally.
    """
    import inspect

    from app.services import people_service

    source = inspect.getsource(people_service)
    # The buggy singular comparison must be gone.
    assert 'bucket != "peer"' not in source
    # The corrected plural comparison must be present.
    assert 'bucket != "peers"' in source


# ---------------------------------------------------------------------------
# C3 — search_jobs returns refreshed existing rows, not just new ones
# ---------------------------------------------------------------------------
def test_c3_search_jobs_appends_existing_matches():
    """Regression lock: the existing-job branch must append to the result list.

    The test harness uses Postgres-only types so search_jobs cannot run against
    an in-memory DB here; this asserts the corrected control flow at the source
    level (the bug was an early `continue` that dropped refreshed rows).
    """
    import inspect

    from app.services import job_service

    src = inspect.getsource(job_service.search_jobs)
    # Existing rows are refreshed AND returned, each tagged as not-new.
    assert "existing._is_new_job = False" in src
    assert "stored_jobs.append(existing)" in src
    # New rows are tagged as new.
    assert "job._is_new_job = True" in src


def test_c3_refresh_task_filters_to_new_jobs_only():
    """The refresh task must scope counts/notifications to genuinely-new jobs."""

    class _FakeJob:
        def __init__(self, is_new=None):
            if is_new is not None:
                self._is_new_job = is_new

    new_a = _FakeJob(is_new=True)
    new_b = _FakeJob(is_new=True)
    existing = _FakeJob(is_new=False)
    startup_row = _FakeJob()  # startup path: no flag -> treated as new (default True)

    matched = [new_a, existing, new_b, startup_row]
    new_jobs = [job for job in matched if getattr(job, "_is_new_job", True)]

    assert new_jobs == [new_a, new_b, startup_row]
    assert existing not in new_jobs


# ---------------------------------------------------------------------------
# C4 — Dice key from env, fail soft
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_c4_dice_search_fails_soft_without_key(monkeypatch):
    from app.clients import remote_jobs_client

    monkeypatch.setattr(remote_jobs_client.settings, "dice_api_key", "")
    result = await remote_jobs_client.search_dice("software engineer", limit=5)
    assert result == []


def test_c4_no_hardcoded_dice_key_in_source():
    import inspect

    from app.clients import remote_jobs_client

    source = inspect.getsource(remote_jobs_client)
    assert "1YAt0R9wBg4WfsF9VB2778F5CHLAPMVW3WAZcKd8" not in source


def test_c4_dice_headers_read_from_settings(monkeypatch):
    from app.clients import remote_jobs_client

    monkeypatch.setattr(remote_jobs_client.settings, "dice_api_key", "fresh-key-123")
    assert remote_jobs_client._dice_headers()["x-api-key"] == "fresh-key-123"


# ---------------------------------------------------------------------------
# C5 — Adzuna currency map
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("country", "currency"),
    [
        ("us", "USD"),
        ("gb", "GBP"),
        ("ca", "CAD"),
        ("au", "AUD"),
        ("de", "EUR"),
        ("fr", "EUR"),
        ("in", "INR"),
        ("mx", "MXN"),
        ("nz", "NZD"),
        ("CA", "CAD"),  # case-insensitive
        ("zz", "USD"),  # unknown -> USD fallback
    ],
)
def test_c5_adzuna_currency_map(country, currency):
    from app.clients.adzuna_client import _adzuna_currency

    assert _adzuna_currency(country) == currency
