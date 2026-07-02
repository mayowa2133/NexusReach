"""The feed-refresh mutex must fail OPEN, unlike the debounce (fail-closed).

A Redis outage must not stop feed refreshes — losing mutual exclusion is the
pre-lock status quo, while a fail-closed lock would silently freeze every
user's refresh cycle until Redis returns.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.clients import search_cache_client

pytestmark = pytest.mark.asyncio


async def test_acquire_lock_returns_true_when_slot_is_free():
    redis = MagicMock()
    redis.set = AsyncMock(return_value=True)
    with patch.object(search_cache_client, "_client", return_value=redis):
        assert await search_cache_client.acquire_lock("k", ttl_seconds=60) is True
    redis.set.assert_awaited_once_with("k", "1", ex=60, nx=True)


async def test_acquire_lock_returns_false_when_held():
    redis = MagicMock()
    redis.set = AsyncMock(return_value=None)  # NX miss
    with patch.object(search_cache_client, "_client", return_value=redis):
        assert await search_cache_client.acquire_lock("k", ttl_seconds=60) is False


async def test_acquire_lock_fails_open_on_redis_error():
    redis = MagicMock()
    redis.set = AsyncMock(side_effect=ConnectionError("redis down"))
    with patch.object(search_cache_client, "_client", return_value=redis):
        assert await search_cache_client.acquire_lock("k", ttl_seconds=60) is True


async def test_release_lock_swallows_redis_errors():
    redis = MagicMock()
    redis.delete = AsyncMock(side_effect=ConnectionError("redis down"))
    with patch.object(search_cache_client, "_client", return_value=redis):
        await search_cache_client.release_lock(f"k:{uuid.uuid4()}")  # must not raise
