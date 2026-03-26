"""Tests for the per-user discovery daily rate limiter."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.utils.discovery_rate_limit import check_discovery_rate_limit


@pytest.fixture()
def mock_redis():
    """Create a mock async Redis client with pipeline support."""
    pipe = AsyncMock()
    pipe.execute = AsyncMock()

    r = AsyncMock()
    r.pipeline = MagicMock(return_value=pipe)
    r.aclose = AsyncMock()
    return r, pipe


@pytest.mark.asyncio()
async def test_allows_request_under_limit(mock_redis):
    r, pipe = mock_redis
    # First pipeline: zremrangebyscore + zcard → count = 5
    pipe.execute.side_effect = [
        [None, 5],   # cleanup + count
        [None, None],  # zadd + expire
    ]

    with (
        patch("app.utils.discovery_rate_limit.aioredis") as mock_aioredis,
        patch("app.utils.discovery_rate_limit.settings") as mock_settings,
    ):
        mock_aioredis.from_url.return_value = r
        mock_settings.redis_url = "redis://localhost:6379/0"
        mock_settings.discovery_daily_limit = 100

        # Should not raise
        await check_discovery_rate_limit(
            user_id="00000000-0000-0000-0000-000000000001"
        )


@pytest.mark.asyncio()
async def test_blocks_request_over_limit(mock_redis):
    r, pipe = mock_redis
    # Count = 100, which equals the limit
    pipe.execute.side_effect = [
        [None, 100],
    ]

    with (
        patch("app.utils.discovery_rate_limit.aioredis") as mock_aioredis,
        patch("app.utils.discovery_rate_limit.settings") as mock_settings,
    ):
        mock_aioredis.from_url.return_value = r
        mock_settings.redis_url = "redis://localhost:6379/0"
        mock_settings.discovery_daily_limit = 100

        with pytest.raises(HTTPException) as exc_info:
            await check_discovery_rate_limit(
                user_id="00000000-0000-0000-0000-000000000001"
            )
        assert exc_info.value.status_code == 429
        assert "Daily discovery limit" in str(exc_info.value.detail)


@pytest.mark.asyncio()
async def test_allows_request_when_redis_unavailable():
    """If Redis is down, requests should still be allowed."""
    with (
        patch("app.utils.discovery_rate_limit.aioredis") as mock_aioredis,
        patch("app.utils.discovery_rate_limit.settings") as mock_settings,
    ):
        broken_redis = AsyncMock()
        broken_redis.pipeline = MagicMock(side_effect=ConnectionError("Redis down"))
        broken_redis.aclose = AsyncMock()
        mock_aioredis.from_url.return_value = broken_redis
        mock_settings.redis_url = "redis://localhost:6379/0"
        mock_settings.discovery_daily_limit = 100

        # Should not raise — graceful degradation
        await check_discovery_rate_limit(
            user_id="00000000-0000-0000-0000-000000000001"
        )


@pytest.mark.asyncio()
async def test_different_users_independent(mock_redis):
    """Each user gets their own rate-limit window."""
    r, pipe = mock_redis
    keys_seen: list[str] = []

    original_zremrangebyscore = pipe.zremrangebyscore

    def capture_key(*args, **kwargs):
        if args:
            keys_seen.append(str(args[0]))
        return original_zremrangebyscore(*args, **kwargs)

    pipe.zremrangebyscore = capture_key
    pipe.execute.return_value = [None, 0]

    # Reset side_effect so execute always returns under-limit
    pipe.execute.side_effect = [
        [None, 0], [None, None],
        [None, 0], [None, None],
    ]

    with (
        patch("app.utils.discovery_rate_limit.aioredis") as mock_aioredis,
        patch("app.utils.discovery_rate_limit.settings") as mock_settings,
    ):
        mock_aioredis.from_url.return_value = r
        mock_settings.redis_url = "redis://localhost:6379/0"
        mock_settings.discovery_daily_limit = 100

        await check_discovery_rate_limit(
            user_id="00000000-0000-0000-0000-000000000001"
        )
        await check_discovery_rate_limit(
            user_id="00000000-0000-0000-0000-000000000002"
        )

    # Verify both user keys appeared
    assert any("000000000001" in k for k in keys_seen)
    assert any("000000000002" in k for k in keys_seen)
