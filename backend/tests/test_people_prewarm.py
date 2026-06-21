"""Tests for discovery-only people pre-warm that makes Find People instant."""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest


def _make_session(mock_db):
    class FakeSession:
        async def __aenter__(self):
            return mock_db

        async def __aexit__(self, *args):
            return False

    return FakeSession()


@pytest.mark.asyncio()
async def test_prewarm_skips_when_company_already_warm():
    """A company with a healthy cached roster should not spend API calls again."""
    from app.tasks.auto_prospect import _prewarm_company_people, PREWARM_SKIP_THRESHOLD

    mock_db = AsyncMock()
    with (
        patch("app.tasks.auto_prospect.async_session", return_value=_make_session(mock_db)),
        patch(
            "app.services.known_people_service.get_known_people_count",
            new=AsyncMock(return_value=PREWARM_SKIP_THRESHOLD),
        ),
        patch(
            "app.services.people.search_people_at_company",
            new=AsyncMock(),
        ) as mock_search,
    ):
        result = await _prewarm_company_people(uuid.uuid4(), "Stripe")

    assert result["skipped"] is True
    assert result["warmed"] is False
    mock_search.assert_not_awaited()


@pytest.mark.asyncio()
async def test_prewarm_runs_search_when_cache_cold():
    """A cold company should warm the cache (persist=False) without saving CRM rows."""
    from app.tasks.auto_prospect import _prewarm_company_people

    mock_db = AsyncMock()
    # persist=False returns a cache-warm summary, not persisted Person buckets.
    search_result = {
        "company": object(),
        "cache_warmed": True,
        "candidate_count": 6,
        "recruiters": [],
        "hiring_managers": [],
        "peers": [],
        "your_connections": [],
    }
    with (
        patch("app.tasks.auto_prospect.async_session", return_value=_make_session(mock_db)),
        patch(
            "app.services.known_people_service.get_known_people_count",
            new=AsyncMock(return_value=0),
        ),
        patch(
            "app.services.people.search_people_at_company",
            new=AsyncMock(return_value=search_result),
        ) as mock_search,
    ):
        result = await _prewarm_company_people(uuid.uuid4(), "Stripe")

    assert result["warmed"] is True
    assert result["skipped"] is False
    assert result["people_found"] == 6
    mock_search.assert_awaited_once()
    # Pre-warm must never persist Person CRM rows for the user.
    assert mock_search.await_args.kwargs["persist"] is False


@pytest.mark.asyncio()
async def test_maybe_prewarm_dedupes_ranks_and_caps():
    """Distinct companies, ranked by best score, capped at the configured max."""
    from app.services.jobs import storage

    jobs = [
        SimpleNamespace(company_name=f"Co{i}", match_score=float(i))
        for i in range(12)
    ]
    # Duplicate company whose better score should lift it to the top.
    jobs.append(SimpleNamespace(company_name="Co0", match_score=100.0))
    # Blank company must be ignored entirely.
    jobs.append(SimpleNamespace(company_name="  ", match_score=50.0))

    with (
        patch(
            "app.services.settings_service.is_people_prewarm_enabled",
            new=AsyncMock(return_value=True),
        ),
        patch("app.tasks.auto_prospect.prewarm_company_people") as mock_task,
    ):
        await storage._maybe_prewarm_people(AsyncMock(), uuid.uuid4(), jobs)

    assert mock_task.delay.call_count == storage.PREWARM_MAX_COMPANIES
    queued = [call.args[1] for call in mock_task.delay.call_args_list]
    assert queued[0] == "Co0"  # lifted by the duplicate's 100.0 score
    assert "  " not in queued  # blank company never queued
    assert len(set(queued)) == len(queued)  # no duplicate companies queued


@pytest.mark.asyncio()
async def test_maybe_prewarm_respects_opt_out():
    """When the user disables pre-warm, no tasks are queued."""
    from app.services.jobs import storage

    jobs = [SimpleNamespace(company_name="Stripe", match_score=1.0)]
    with (
        patch(
            "app.services.settings_service.is_people_prewarm_enabled",
            new=AsyncMock(return_value=False),
        ),
        patch("app.tasks.auto_prospect.prewarm_company_people") as mock_task,
    ):
        await storage._maybe_prewarm_people(AsyncMock(), uuid.uuid4(), jobs)

    mock_task.delay.assert_not_called()
