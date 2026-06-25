"""Tests for the button-free POST /api/jobs/ensure-fresh feed nudge."""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.database import get_db
from app.main import app

pytestmark = pytest.mark.asyncio


def _db_with(*, pref_count: int, last_refreshed, job_count: int) -> MagicMock:
    """A mock async session whose two execute() calls answer the endpoint.

    First execute -> (saved-search count, max last_refreshed); second -> job count.
    """
    db = MagicMock()
    pref_result = MagicMock()
    pref_result.one.return_value = (pref_count, last_refreshed)
    count_result = MagicMock()
    count_result.scalar.return_value = job_count
    db.execute = AsyncMock(side_effect=[pref_result, count_result])
    return db


async def _call(client, db):
    async def _override_db():
        yield db

    app.dependency_overrides[get_db] = _override_db
    try:
        return await client.post("/api/jobs/ensure-fresh", json={})
    finally:
        app.dependency_overrides.pop(get_db, None)


async def test_noop_without_saved_search(client):
    """No enrolled saved search -> nothing fires (user hasn't picked targets)."""
    db = _db_with(pref_count=0, last_refreshed=None, job_count=0)
    with (
        patch("app.clients.search_cache_client.acquire_debounce", new=AsyncMock(return_value=True)) as deb,
        patch("app.tasks.jobs.discover_for_user") as disc,
        patch("app.tasks.jobs.refresh_single_user_feeds") as refr,
    ):
        resp = await _call(client, db)
    assert resp.status_code == 200
    assert resp.json() == {"triggered": False, "mode": None}
    deb.assert_not_called()
    disc.delay.assert_not_called()
    refr.delay.assert_not_called()


async def test_empty_feed_triggers_cold_start_discover(client, mock_user_id):
    db = _db_with(pref_count=2, last_refreshed=None, job_count=0)
    with (
        patch("app.clients.search_cache_client.acquire_debounce", new=AsyncMock(return_value=True)),
        patch("app.tasks.jobs.discover_for_user") as disc,
        patch("app.tasks.jobs.refresh_single_user_feeds") as refr,
    ):
        resp = await _call(client, db)
    assert resp.json() == {"triggered": True, "mode": "discover"}
    disc.delay.assert_called_once_with(str(mock_user_id))
    refr.delay.assert_not_called()


async def test_warm_but_stale_feed_triggers_light_refresh(client, mock_user_id):
    stale = datetime.now(timezone.utc) - timedelta(minutes=45)
    db = _db_with(pref_count=1, last_refreshed=stale, job_count=12)
    with (
        patch("app.clients.search_cache_client.acquire_debounce", new=AsyncMock(return_value=True)),
        patch("app.tasks.jobs.discover_for_user") as disc,
        patch("app.tasks.jobs.refresh_single_user_feeds") as refr,
    ):
        resp = await _call(client, db)
    assert resp.json() == {"triggered": True, "mode": "refresh"}
    refr.delay.assert_called_once_with(str(mock_user_id))
    disc.delay.assert_not_called()


async def test_fresh_feed_is_noop(client):
    fresh = datetime.now(timezone.utc) - timedelta(minutes=2)
    db = _db_with(pref_count=1, last_refreshed=fresh, job_count=12)
    with (
        patch("app.clients.search_cache_client.acquire_debounce", new=AsyncMock(return_value=True)) as deb,
        patch("app.tasks.jobs.discover_for_user") as disc,
        patch("app.tasks.jobs.refresh_single_user_feeds") as refr,
    ):
        resp = await _call(client, db)
    assert resp.json() == {"triggered": False, "mode": None}
    deb.assert_not_called()  # returns before acquiring the debounce slot
    disc.delay.assert_not_called()
    refr.delay.assert_not_called()


async def test_debounce_suppresses_repeat_nudge(client):
    """Even on an empty feed, a held debounce slot means no re-trigger."""
    db = _db_with(pref_count=2, last_refreshed=None, job_count=0)
    with (
        patch("app.clients.search_cache_client.acquire_debounce", new=AsyncMock(return_value=False)),
        patch("app.tasks.jobs.discover_for_user") as disc,
        patch("app.tasks.jobs.refresh_single_user_feeds") as refr,
    ):
        resp = await _call(client, db)
    assert resp.json() == {"triggered": False, "mode": None}
    disc.delay.assert_not_called()
    refr.delay.assert_not_called()


# --- POST /api/jobs/discover-occupations (chip-driven discovery) -------------


async def test_discover_occupations_triggers_for_valid_occupations(client, mock_user_id):
    with (
        patch("app.clients.search_cache_client.acquire_debounce", new=AsyncMock(return_value=True)),
        patch("app.tasks.jobs.discover_occupations_for_user") as task,
    ):
        resp = await client.post(
            "/api/jobs/discover-occupations",
            json={"occupations": ["marketing", "not_a_real_occ"]},
        )
    assert resp.status_code == 200
    assert resp.json() == {"triggered": True, "mode": "discover"}
    task.delay.assert_called_once()
    args = task.delay.call_args.args
    assert args[0] == str(mock_user_id)
    assert args[1] == ["marketing"]  # unknown occupation filtered out


async def test_discover_occupations_noop_when_none_valid(client):
    with (
        patch("app.clients.search_cache_client.acquire_debounce", new=AsyncMock(return_value=True)) as deb,
        patch("app.tasks.jobs.discover_occupations_for_user") as task,
    ):
        resp = await client.post(
            "/api/jobs/discover-occupations", json={"occupations": ["nonsense"]}
        )
    assert resp.json() == {"triggered": False, "mode": None}
    deb.assert_not_called()
    task.delay.assert_not_called()


async def test_discover_occupations_debounced(client):
    with (
        patch("app.clients.search_cache_client.acquire_debounce", new=AsyncMock(return_value=False)),
        patch("app.tasks.jobs.discover_occupations_for_user") as task,
    ):
        resp = await client.post(
            "/api/jobs/discover-occupations", json={"occupations": ["marketing"]}
        )
    assert resp.json() == {"triggered": False, "mode": None}
    task.delay.assert_not_called()
